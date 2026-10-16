# Звіт аудиту безпеки — «Електронний деканат»

| Поле | Значення |
|---|---|
| Аудитор | Недождій Ігор, група Б2F5013ОН24 |
| Дата аудиту | 2026-10-16 |
| Версія системи | commit `a9d4b6f` (ЗПР-2, етап 3) |
| Обсяг (scope) | API FastAPI, БД SQLite, Docker-образ, Nginx, залежності |
| Поза обсягом | фронтенд, хост-ОС, соціальна інженерія (лише оцінка ризику) |
| Методи | STRIDE, OWASP Top 10 (2021), Trivy, pip-audit, Bandit, security_check.sh, pentest_mini.sh |

## 1. Резюме для керівництва

Система «Електронний деканат» за підсумками ЗПР-1 і ЗПР-2 має багаторівневий захист: автентифікацію (bcrypt + JWT), RBAC, валідацію Pydantic, шифрування PII (Fernet + сліпий індекс), журнал аудиту 5W з виявленням Brute Force, hardened-контейнер під HTTPS. Автоматичний чеклист `security_check.sh` проходить із `FAIL: 0` (лише 1 WARN — знахідки pip-audit), Bandit не виявив жодної проблеми в коді, а всі 12 мінітестів на вразливості пройдено («✅ захищено»).

Головний залишковий ризик — **застарілі залежності** (найвищий ризик R7 у матриці, 16/25): Trivy бачить 1 CRITICAL і 8 HIGH у Python-пакетах, pip-audit — 17 вразливостей у 3 пакетах (starlette, python-jose, ecdsa). Частину закрито оновленням пінів на етапі 3 (`python-jose 3.3.0→3.5.0`, `python-multipart 0.0.9→0.0.32`, `bleach 6.1.0→6.4.0`). Решта — прийнятий ризик з обґрунтуванням (HS256, відсутність attacker-controlled ключів) та планом міграції на PyJWT і FastAPI 0.14x/starlette 1.x.

Головні рекомендації: (1) оновити FastAPI (а разом з ним starlette) і замінити python-jose на PyJWT; (2) винести журнал аудиту на зовнішнє сховище та впровадити MFA для викладачів/адміністраторів.

| Критичні | Високі | Середні | Низькі |
|---|---|---|---|
| 1 | 6 | 4 | 3 |

Із 14 знахідок **4 виправлено** під час ЗПР-2 (етап 3), решта 10 — прийнятий ризик або план із обґрунтуванням.

## 2. Інвентаризація активів

| Актив | Тип | Критичність | Обґрунтування |
|---|---|---|---|
| data/app.db | Дані | Критичний | ПІБ, email, оцінки студентів |
| ENCRYPTION_KEY, BLIND_INDEX_KEY, JWT_SECRET_KEY | Секрети | Критичний | Компрометація = доступ до PII / втрата даних |
| data/backups/*.db.enc | Дані | Високий | Повна (зашифрована) копія БД |
| audit_log | Дані | Середній | Докази для розслідувань і KPI |
| Код застосунку (образ) | Код | Високий | Логіка доступу, шифрування, аудиту |
| nginx/certs/selfsigned.key | Секрет | Середній | Приватний ключ TLS (dev; у prod — Let's Encrypt) |
| Docker-образ (base python:3.11-slim) | Залежності | Високий | Джерело більшості знахідок Trivy (OS + Python) |

## 3. Реалізовані шари захисту (Defense in Depth)

| Шар | Механізм | Де (файл / робота) |
|---|---|---|
| Автентифікація | bcrypt, JWT access+refresh (type-перевірка) | ЗПР-1, `app/security.py`, `app/auth/` |
| Авторизація | RBAC admin/teacher/student (ролі з БД) | ЗПР-1, `app/auth/dependencies.py` |
| Веб-рівень | Pydantic, bleach, CSP, CORS без `*`, slowapi | ЗПР-1, `app/middleware/`, `app/schemas.py` |
| Шифрування даних | Fernet для email/phone, сліпий індекс HMAC, зашифрований бекап | ЗПР-2, `app/crypto/`, `scripts/backup_db.py` |
| Аудит і моніторинг | audit_log 5W, Brute Force, security-stats | ЗПР-2, `app/audit/` |
| Середовище | non-root appuser, read-only FS, cap_drop ALL, no-new-privileges, HTTPS | ЗПР-2, `Dockerfile`, `docker-compose.yml`, `nginx/` |
| DevSecOps | Trivy, pip-audit, Bandit, `security_check.sh` | ЗПР-2, `reports/` |

## 4. Модель загроз STRIDE

| STRIDE | Загроза | Реалізований контрзахід | Залишковий ризик |
|---|---|---|---|
| Spoofing | Підбір пароля викладача; підробка JWT | bcrypt, HS256 з `algorithms=["HS256"]`, slowapi (5/min) + детектор Brute Force | Немає MFA; HS256 → RS256 як розвиток |
| Tampering | Студент змінює оцінку; підміна шифротексту в БД | RBAC `require_role` (ролі з БД), Pydantic allow-list, HMAC Fernet (підміна → `[ПОМИЛКА РОЗШИФРУВАННЯ]`) | Записи журналу не підписані |
| Repudiation | Викладач заперечує виставлену оцінку | `assigned_by`, audit_log 5W, `data_change` (old→new) | Журнал у тій самій БД: адмін БД може стерти |
| Information Disclosure | Витік app.db або бекапу | Fernet для email/phone, зашифрований бекап, HTTPS/TLS 1.2+ | `full_name` відкритий; ключі на тому ж хості |
| Denial of Service | Флуд `/auth/login`; блокування чужого акаунта | slowapi, Nginx `limit_req`, `client_max_body_size 1m`, детектор Brute Force | Lockout за логіном можна зловживати (5 хв) |
| Elevation of Privilege | Студент → admin; вихід з контейнера | RBAC, non-root appuser, `read_only`, `cap_drop: ALL`, `no-new-privileges` | Немає seccomp-профілю; IDOR у нових ендпоінтах |

## 5. Матриця ризиків (залишковий ризик)

Ризик = Ймовірність (1–5) × Вплив (1–5). Рівні: 1–4 низький, 5–9 середній, 10–15 високий, 16–25 критичний.

| # | Загроза | Й (1–5) | В (1–5) | Ризик | Рівень | Обґрунтування |
|---|---|---|---|---|---|---|
| R1 | Brute Force | 4 | 3 | 12 | Високий | Публічний `/auth/login`; є slowapi + детектор, але без MFA і CAPTCHA |
| R2 | SQL Injection | 1 | 5 | 5 | Середній | Лише ORM/`text()` з параметрами; T10 підтвердив 401; вплив був би критичним |
| R3 | Stored XSS | 2 | 3 | 6 | Середній | Pydantic allow-list + bleach; T9 → 422; залишається `full_name` у відповідях |
| R4 | Крадіжка JWT | 3 | 4 | 12 | Високий | access 30 хв; токен у пам'яті клієнта; немає відкликання/rotation |
| R5 | Витік БД або бекапу | 2 | 5 | 10 | Високий | PII зашифровано, бекап зашифрований; втрата обох = повний розкриття |
| R6 | Втрата ENCRYPTION_KEY | 2 | 5 | 10 | Високий | Бекап не допоможе (той самий ключ); ключ на тому ж хості |
| R7 | Вразлива залежність | 4 | 4 | 16 | Критичний | Trivy 1 CRITICAL + 8 HIGH, pip-audit 17/3 (starlette, python-jose, ecdsa) |
| R8 | Фішинг викладача | 3 | 4 | 12 | Високий | Людський фактор; частково знижує аудит і RBAC, але немає MFA |
| R9 | Lockout-акаунта DoS | 3 | 3 | 9 | Середній | Детектор блокує за логіном → можна навмисно заблокувати колегу на 5 хв |
| R10 | Підробка/видалення журналу | 2 | 3 | 6 | Середній | audit_log без підпису, у тій самій БД (Repudiation) |
| R11 | IDOR у нових ендпоінтах | 2 | 4 | 8 | Середній | Перевірка власності ресурсу перевірена частково (T7); нові маршрути — вручну |
| R12 | Вихід з контейнера (EoP) | 1 | 5 | 5 | Середній | non-root + cap_drop + no-new-privileges; немає seccomp/AppArmor |

## 6. Знахідки та рекомендації

| ID | Рівень | Знахідка | Доказ | Рекомендація | Статус |
|---|---|---|---|---|---|
| F-01 | High | Fallback JWT-секрет у `config.py` і `:-dev…` у compose (ЗПР-1) | `security_check.sh` (було FAIL: 3 на ЗПР-1) | Прибрати fallback, fail-fast при відсутньому ключі | **Виправлено (етап 3)** |
| F-02 | High | Застарілий `starlette 0.37.2` через `fastapi==0.111.0` (DoS/SSRF: CVE-2024-47874, CVE-2026-48818, CVE-2026-54283) | `reports/pip-audit.txt`, `reports/trivy.txt` | Оновити FastAPI → starlette ≥1.3.1 (потребує мажорного оновлення) | Прийнято ризик + план міграції |
| F-03 | High | `python-multipart 0.0.9` — DoS / arbitrary file write | `reports/pip-audit.txt` | Оновити пін | **Виправлено (0.0.32)**, у рантаймі не використовується (немає Form/File) |
| F-04 | High | `bleach 6.1.0` — 2 CVE (GHSA-gj48…, GHSA-8rfp…) | `reports/pip-audit.txt` | Оновити пін | **Виправлено (6.4.0)** |
| F-05 | High | `python-jose 3.3.0` — algorithm confusion (CVE-2024-33663, фікс у 3.4.0) | `reports/trivy.txt` | Оновити пін | **Виправлено (3.5.0)** |
| F-06 | Critical | `python-jose` CVE-2026-85394 — algorithm confusion через DER-ключ (без виправлення станом на 3.5.0) | `reports/pip-audit.txt`, `reports/trivy.txt` | Міграція на PyJWT; зараз використовується лише HS256 із серверним секретом, немає JWKS/асиметричних ключів від клієнта → не експлуатується | Прийнято ризик (обґрунтовано) |
| F-07 | High | `ecdsa 0.19.2` — CVE-2024-23342 (Minerva; виправлення немає) | `reports/trivy.txt` | Замінити бібліотеку; ECDSA не використовується (HS256) | Прийнято ризик |
| F-08 | Medium | OS-пакети base-образу (util-linux, ncurses, systemd, perl) — 44 HIGH | `reports/trivy.txt` | Регулярний rebuild на оновленому `python:3.11-slim`, пін digest base-образу | Прийнято + план |
| F-09 | Medium | Lockout за логіном: зловмисник навмисно блокує чужий акаунт на 5 хв | Код `app/audit/detector.py`, тест T12 | Комбінувати з CAPTCHA/прогресивною затримкою; сповіщати користувача | Прийнято (компроміс задокументовано) |
| F-10 | Medium | `audit_log` не підписаний і лежить у тій самій БД | `app/models.py`, `app/audit/` | Експорт логів у зовнішнє WORM/centralized-сховище (SIEM) | Прийнято + план |
| F-11 | Medium | Відсутній MFA для викладачів/адміністраторів | Модель загроз, R8 | TOTP/WebAuthn для привілейованих ролей | План |
| F-12 | Low | `--forwarded-allow-ips "*"` довіряє будь-якому `X-Forwarded-For` | `Dockerfile` (CMD) | Прийнятно лише тому, що 8000 відкрито на 127.0.0.1; звузити IP у prod | Прийнято ризик |
| F-13 | Low | Self-signed TLS-сертифікат | `scripts/generate_cert.sh` | Let's Encrypt / корпоративний CA у production | Прийнято (dev) |
| F-14 | Low | `full_name` і `username` зберігаються відкрито (PII) | `app/models.py` | Розширити Fernet на `full_name` за потреби | Прийнято ризик |

## 7. Чеклист OWASP Top 10 (2021)

| ID | Категорія | Статус | Доказ / коментар |
|---|---|---|---|
| A01 | Broken Access Control | ✅ | T5/T6/T7 → 403 для студента; `require_role`, ролі з БД; `access_denied` у журналі |
| A02 | Cryptographic Failures | ✅ | bcrypt (паролі), Fernet (email/phone), HMAC-сліпий індекс, TLS 1.2+, секрети лише в `.env` |
| A03 | Injection | ✅ | Лише ORM / параметризований `text()`; Pydantic allow-list; bleach; T9 → 422, T10 → 401 |
| A04 | Insecure Design | ⚠️ | Є модель загроз STRIDE і задокументований компроміс lockout; немає формального threat-model review |
| A05 | Security Misconfiguration | ✅ | Security Headers, CORS без `*`, `server_tokens off`, без fallback-секретів, `read_only`, `cap_drop` |
| A06 | Vulnerable and Outdated Components | ⚠️ | Trivy/pip-audit: частину пінів оновлено; starlette/python-jose/ecdsa — прийнято + план |
| A07 | Identification and Authentication Failures | ✅ | Rate limit 5/min, детектор Brute Force, `exp`, refresh ≠ access (T4), однакова відповідь на невірний логін/пароль |
| A08 | Software and Data Integrity Failures | ✅ | HMAC Fernet, пін-версії, перевірене відновлення бекапу (`integrity_check=ok`) |
| A09 | Security Logging and Monitoring Failures | ✅ | audit_log 5W, перегляд журналу теж логується (`audit_log_viewed`), JSON-логи без паролів/токенів |
| A10 | SSRF | N/A | Сервер не виконує запити на URL від користувача; немає відповідних ендпоінтів |

## 8. Результати автоматизованого сканування

| Інструмент | Тип | CRITICAL | HIGH | MEDIUM | Дія |
|---|---|---|---|---|---|
| Trivy | Container SCA | 1 | 52 | 0 | 1 CRITICAL (python-jose, unchecked upstream) + 8 HIGH (Python) + 44 HIGH (OS base-образу); оновлені піни, решта — прийнято + план |
| pip-audit | Python SCA | — | 17 вразливостей у 3 пакетах | — | Зменшено з 38/5 до 17/3 оновленням python-jose, python-multipart, bleach |
| Bandit | SAST | — | 0 | 0 | 1101 рядок коду, 0 проблем |
| security_check.sh | Конфігурація | FAIL: 0 | WARN: 1 | | **SECURITY CHECK PASSED** (WARN — знахідки pip-audit) |

Повні звіти: `reports/trivy.txt`, `reports/pip-audit.txt`, `reports/bandit.txt`, `reports/security_check.txt`.

## 9. Результати мінітестів

`scripts/pentest_mini.sh` (через Nginx, `https://localhost`):

| Тест | Фактично | Очікується | Висновок |
|---|---|---|---|
| T1 Доступ без токена (/auth/me) | 401 | 401 | ✅ захищено |
| T2 JWT з підробленим payload | 401 | 401 | ✅ захищено |
| T3 JWT з alg=none | 401 | 401 | ✅ захищено |
| T4 Refresh token замість access | 401 | 401 | ✅ захищено |
| T5 Студент → /admin/users | 403 | 403 | ✅ захищено |
| T6 Студент → /admin/audit-log | 403 | 403 | ✅ захищено |
| T7 Студент → чужі оцінки через /teachers | 403 | 403 | ✅ захищено |
| T8 Адмін → /admin/audit-log (контроль) | 200 | 200 | ✅ захищено |
| T9 XSS у full_name при реєстрації | 422 | 422 | ✅ захищено |
| T10 SQLi у логіні (`' OR '1'='1`) | 401 | 401 422 429 | ✅ захищено |
| T11 Email у БД зашифровано | gAAAA | gAAAA | ✅ захищено |
| T12 Brute Force (8 спроб) | 429 | 429 | ✅ захищено |

**Ручний тест (CORS):** `GET /health` з `Origin: https://evil.example` — у відповіді **відсутній** заголовок `Access-Control-Allow-Origin` (є лише `access-control-allow-credentials: true`). Браузер не надасть доступу чужому джерелу → контрзахід працює.

## 10. Моніторинг і KPI

| Показник | Значення | Джерело |
|---|---|---|
| Всього подій / 24 год | 120 | `/admin/security-stats` |
| Невдалих входів / 24 год | 8 | `/admin/security-stats` |
| Brute Force алертів | 1 | `/admin/security-stats` |
| Відмов у доступі (access_denied) | 4 | `/admin/security-stats` |
| Змін даних (data_change) | 1 | `/admin/security-stats` |
| Server errors (5xx) | 0 | `/admin/security-stats` |
| Top failure IP | 172.18.0.1 (97) | `/admin/security-stats` |
| MTTD (тест Brute Force) | ≈ 62 с | audit_log: перший `login_failed` 15:31:08 → `brute_force_detected` 15:32:10 |
| MTTR (тест Brute Force) | < 0,01 с | audit_log: `brute_force_detected` 15:32:10.3468 → 429 (`brute_force_blocked`) 15:32:10.3499 |
| Останній бекап / відновлення перевірено | 2026-10-16 16:02 / **так** | `scripts/backup_db.py`, `restore_db` → `integrity_check=ok, users=4` |

## 11. План покращень

| Пріоритет | Захід | Яку загрозу закриває | Зусилля |
|---|---|---|---|
| 1 | Оновити FastAPI (starlette ≥1.3.1) і мігрувати python-jose → PyJWT | R7 (вразливі залежності), F-02/F-06 | 1–2 дні |
| 2 | MFA (TOTP/WebAuthn) для викладачів та адміністраторів | R8 (фішинг), R1/R4 (крадіжка облікових даних) | 2–3 дні |
| 3 | Експорт audit_log у зовнішнє WORM/SIEM-сховище з підписом | R10 (Repudiation), A09 | 1–2 дні |
| 4 | Керування секретами у Vault/KMS; ключі не на тому ж хості, ніж БД | R5/R6 (витік/втрата ключа) | 2–3 дні |
| 5 | seccomp/AppArmor-профіль + пін digest base-образу, регулярний rebuild | R12, F-08 | 1 день |
| 6 | Прогресивна затримка/CAPTCHA замість жорсткого lockout | R9 (lockout-DoS) | 1 день |
| 7 | Розширити шифрування на `full_name`, ротація ключа через `ENCRYPTION_KEY_OLD` | F-14 (PII), R5 | 1 день |

## 12. Висновок

Система **готова до експлуатації в контрольованому середовищі** (навчальний стенд / внутрішній периметр) за умови, що секрети зберігаються поза репозиторієм, HTTPS термінується Nginx, а порт 8000 доступний лише локально. Усі базові контрзаходи (шифрування PII, аудит, RBAC, rate limiting, hardening контейнера) реалізовано й підтверджено мінітестами; критичних експлуатованих вразливостей не знайдено.

Найкритичніший залишковий ризик — **R7: застарілі залежності** (16/25): знайдено 1 CRITICAL і 8 HIGH у Python-пакетах. Частину закрито оновленням пінів, проте `starlette` (через FastAPI 0.111) і `python-jose` (CVE-2026-85394) потребують мажорного оновлення/міграції. Оскільки застосунок використовує лише HS256 із серверним секретом і не довіряє ключам від клієнта, відомі «algorithm confusion» CVE наразі неексплуатовані — тому ризик прийнято з конкретним планом (пункт 1 плану покращень). До виконання цього пункту систему не слід виводити у відкритий публічний периметр без додаткового контролю (WAF, оновлені залежності).
