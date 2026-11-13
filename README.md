# Printer Data Analysis Dashboard (Connected to print_db)

একটি আধুনিক এবং ডায়নামিক **FastAPI** অ্যানালিটিক্স ড্যাশবোর্ড যা সরাসরি আপনার লোকাল MySQL ডাটাবেস **`print_db`** (XAMPP / phpMyAdmin)-এর সাথে কানেক্টেড।

## 📁 প্রজেক্ট স্ট্রাকচার
```
printer-data-anylis/
│
├── main.py              # FastAPI ব্যাকএন্ড ও API রুটস
├── database.py          # MySQL (print_db) কানেকশন ও কোয়েরি লজিক
├── ai_service.py        # Read-only AI business context ও Gemini integration
├── requirements.txt     # ডিপেন্ডেন্সিস (FastAPI, PyMySQL, Uvicorn, Jinja2)
├── run.bat              # এক ক্লিকে সার্ভার চালু করার স্ক্রিপ্ট
├── templates/
│   └── index.html       # ইন্টারেক্টিভ ড্যাশবোর্ড (Tailwind CSS + Chart.js)
└── venv/                # পাইথন ভার্চুয়াল এনভায়রনমেন্ট
```

## 🚀 সার্ভার রান করার নিয়ম
```powershell
.\venv\Scripts\uvicorn.exe main:app --reload --host 127.0.0.1 --port 8000
```
*(অথবা সরাসরি `run.bat` ফাইলে ডাবল ক্লিক করুন)*

## 🌐 ব্রাউজারে দেখুন:
- **ড্যাশবোর্ড**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **FastAPI ইন্টারেক্টিভ সোয়াগার ডক্স**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **phpMyAdmin (print_db)**: [http://localhost/phpmyadmin/index.php?route=/database/structure&db=print_db](http://localhost/phpmyadmin/index.php?route=/database/structure&db=print_db)

## 📊 সংযুক্ত ফিচারসমূহ (`print_db` ডেটা থেকে):
1. **মোট রেভিনিউ ও সেলস (Total Revenue & Sales)**: ১৪,৬৮০+ ইনভয়েসের মোট বিক্রয় (৳৩৯.৮১+ কোটি)।
2. **গুদাম স্টক ভ্যালুয়েশন (Stock Valuation)**: ৫৪৭টি পণ্যের ২৫৪,৩৫০টি আইটেমের মোট বর্তমান মজুদ মূল্য (৳৫.৩৫ কোটি)।
3. **পণ্য ক্যাটালগ (Products Catalog)**: মোট ৯৫৭টি পণ্য (প্রিন্টার, টোনার, রিবন, পেপার ইত্যাদি)।
4. **বি-টু-বি ক্লায়েন্ট (B2B Customers)**: ২,০১০ জন সক্রিয় করপোরেট ক্লায়েন্ট।
5. **১২ মাসের বিক্রয় ট্রেন্ড (Monthly Revenue Trajectory)**: Chart.js চার্ট দিয়ে গত ১২ মাসের রেভিনিউ ও ইনভয়েস ভলিউম অ্যানালাইসিস।
6. **টপ সেলিং প্রিন্টার ও টোনার (Top Selling Products)**: সর্বাধিক বিক্রিত প্রিন্টার, টোনার এবং পেপার আইটেম।
7. **লাইভ সাম্প্রতিক ইনভয়েস (Recent Invoices)**: লেটেস্ট বিক্রয় চালান ও কাস্টমার তথ্য।

## 🤖 AI Business Assistant

Executive Dashboard-এর **AI Assistant** toggle থেকে:

- sales, inventory, customer এবং peak-period data নিয়ে Bengali/English প্রশ্ন করা যায়;
- বর্তমান ডেটা থেকে automated business insights তৈরি করা যায়;
- গত ১২ মাসের trend থেকে directional ৩-মাসের forecast পাওয়া যায়।

AI service শুধুমাত্র read-only analytics snapshot ব্যবহার করে; এটি database query চালায় না এবং কোনো record পরিবর্তন করে না।

### AI configuration

Server চালুর আগে environment variable সেট করুন (অথবা project root-এ `.env` ফাইলে রাখুন):

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
$env:GEMINI_MODEL = "gemini-3.8-flash"  # optional
$env:GEMINI_TIMEOUT_MS = "60000"        # optional; provider timeout in milliseconds
```

API key source code, template বা git-এ রাখবেন না। Key না থাকলে AI endpoints স্পষ্ট configuration error দেবে, dashboard-এর মূল analytics চালু থাকবে।

Optional hardening:

- `DB_CONNECT_TIMEOUT`, `DB_READ_TIMEOUT`, `DB_WRITE_TIMEOUT` connection timeouts override করুন (defaults: 5/30/30 seconds)।
- `DB_READONLY_USER` ও `DB_READONLY_PASSWORD` দিলে AI snapshot শুধুমাত্র read-only database user দিয়ে তৈরি হয়; না দিলে normal DB credentials ব্যবহার হয়। Read-only user-এর analytics tables-এ `SELECT` permission থাকতে হবে।
- AI context সর্বোচ্চ ১২টি ধারাবাহিক month রাখে, missing months zero-fill করে আলাদাভাবে reports করে, এবং forecast সরাসরি supplied trend থেকে গণনা করে। customer phone/address/email payload থেকে বাদ যায়।
- Forecast reliable হতে কমপক্ষে ৩টি observed month দরকার; না থাকলে assistant estimate না করে insufficient data জানায়।

## Reports, alerts ও forecasting

- `/reports`-এ date, product, category এবং customer filter দিয়ে current period বনাম আগের সমান period দেখা যায়।
- Excel/PDF export একই filter ও authenticated report permission ব্যবহার করে।
- Dashboard-এর Smart Alerts low stock এবং ৯০ দিন purchase না করা customer-এর কারণ ও data date দেখায়।
- `/api/forecast/{product_id}` historical monthly quantity থেকে dependency-free linear trend দেয়। তিনটির কম complete month হলে `insufficient_data` ফেরত দেয়; accuracy historical fit-এর MAPE-ভিত্তিক directional indicator, guarantee নয়।
- AI payload-এ customer phone/address/email বাদ থাকে এবং response context-এ source, sales period, missing months ও freshness metadata থাকে। Provider/configuration error 503 এবং data-preparation failure generic 503 হিসেবে দেখানো হয়; assistant read-only। Peak-period insight শুধু তখনই দেওয়া হয় যখন peak data পাওয়া যায়।

## Migration এবং নিরাপত্তা

Application startup-এ `dashboard_auth`, `dashboard_session`-এর compatible columns এবং `dashboard_audit_log` তৈরি/যোগ করা হয়। Existing users, permissions এবং business tables পরিবর্তন করা হয় না। Optional 2FA চালু করতে `dashboard_auth.otp_secret`-এ a TOTP secret সংরক্ষণ করে login payload-এ `otp` পাঠান; `pyotp` dependency ইনস্টল থাকতে হবে। Login প্রতি IP-তে পাঁচটি ব্যর্থ চেষ্টা/পাঁচ মিনিট সীমিত।

প্রথমবার চালুর আগে একটি backup নিন:

```powershell
mysqldump -u root -p --routines --triggers print_db > print_db_backup.sql
```

Restore করার আগে application বন্ধ করে যাচাই করা database-এ করুন:

```powershell
mysql -u root -p print_db < print_db_backup.sql
```

Testing-এ synthetic records ব্যবহার করা হয়েছে; real business data mutate করা হয় না। Excel/PDF packages না থাকলে export endpoint স্পষ্ট `503` দেয়। Forecast seasonality, promotions, stock-outs এবং price changes model করে না। UI labels বর্তমানে প্রধানত English, backend Bengali/English প্রশ্ন এবং explanatory output সমর্থন করে; নতুন translation keys যোগ করা হয়নি।

## Focused tests

```powershell
python -m unittest test_ai_retry.py test_ai_endpoints.py test_upgrade_features.py
```

### Report 01: Product Peak Period

Open `/peak-period` after login. The **Filtered Peak Report** accepts a date
range, product, and category, then shows monthly and yearly quantity/sales
comparisons plus top-product trend lines. The Excel button exports the same
filtered monthly, yearly, and product-trend datasets shown on screen. The
refresh timestamp is returned by the API and loading/empty states are shown in
the UI.

Report 01 uses `sales.SALES_DATE` as the authoritative invoice date and joins
`sales_details` to `product` and `category`. Quantity is
`SUM(sales_details.QTY)` and sales amount is
`SUM(sales_details.QTY * sales_details.UNIT_PRICE)`. Negative quantities are
preserved as returns; rows without a sales date are excluded; months inside a
selected range with no rows are emitted as zero. The current schema does not
provide a separate return-status field, tax-adjusted line amount, or an
explicit calendar table, so returns are identified only by negative quantity
and empty periods are generated in application code. Existing legacy peak
endpoints remain unchanged.

### Report 02: Customer vs Product

Open `/menus/customer-affinity` after login. The **Filtered Customer vs
Product Report** supports date, customer, product, and category filters,
customer/product summaries, purchase history, repeat-purchase charts, and an
Excel export containing the same filtered views.

Customer totals group rows by customer and count purchase frequency with
`COUNT(DISTINCT SALES_ID)`. Product totals group by product and count distinct
customers. Missing `CS_ID` values are labelled `Direct Client`; negative
quantities and amounts are retained as returns. The current schema does not
expose a dedicated discount or net-line-amount field in the report query, so
`QTY * UNIT_PRICE` is treated as the effective amount. Existing customer
affinity explorer endpoints and permissions remain unchanged.
