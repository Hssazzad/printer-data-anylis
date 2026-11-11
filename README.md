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
- গত ২৪ মাসের trend থেকে directional ৩-মাসের forecast পাওয়া যায়।

AI service শুধুমাত্র read-only analytics snapshot ব্যবহার করে; এটি database query চালায় না এবং কোনো record পরিবর্তন করে না।

### AI configuration

Server চালুর আগে environment variable সেট করুন:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
$env:GEMINI_MODEL = "gemini-3.8-flash"  # optional
```

API key source code, template বা git-এ রাখবেন না। Key না থাকলে AI endpoints স্পষ্ট configuration error দেবে, dashboard-এর মূল analytics চালু থাকবে।
