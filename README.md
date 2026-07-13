# GreenSwap 🌍

Find a greener version of anything you buy — with the price shown, so sustainable never feels unaffordable.

## What's in this folder

```
greenswap/
├── app/          Flutter frontend (Duolingo-style UI, green + blue)
├── backend/      Python FastAPI backend (certification lookup + AI estimation)
├── supabase/     Database schema + seed data
└── README.md
```

## Important: extension vs. app

Browser extensions must be written in HTML/JavaScript — Flutter can't build them.
So the plan is:

1. **This Flutter app = your pitch demo.** It shows the full experience end to end.
2. **The backend is the real product.** All logic (certified lookup, AI estimation,
   alternative matching) lives in Python. The future JS extension will call the
   exact same `/analyze` endpoint — nothing gets thrown away.

## How the pipeline works

```
User views a product
        │
        ▼
1. Certified lookup (Supabase)          ──►  found? trust = "Certified" ★
        │ not found
        ▼
2. AI estimation (OpenAI API)           ──►  trust = "AI estimate"
   (materials, category, eco score)
        │
        ▼
3. Find greener alternatives in the
   same category, sorted by eco score,
   filtered near the original price
```

## Setup

### 1. Supabase
- Create a project at supabase.com
- Open the SQL editor and run `supabase/schema.sql`
- Copy your project URL + keys

### 2. Backend
```bash
cd backend
pip install -r requirements.txt
export SUPABASE_URL=...        # from Supabase dashboard
export SUPABASE_SERVICE_KEY=...
export OPENAI_API_KEY=...      # optional; demo works without it
uvicorn main:app --reload
```
Check http://localhost:8000/health

### 3. Flutter app
```bash
cd app
flutter create .    # generates the platform folders (android/ios/web)
flutter pub get
flutter run -d chrome
```

The app works **even with no backend running** — it falls back to built-in
demo data, so your pitch demo can never break on stage. When the backend is
up at localhost:8000, it uses real data automatically.

## Demo script (for your pitch)

1. Open the app → tap "Plastic water bottles, 24-pack"
2. Show the low eco score (22) and the reason
3. Show the two greener swaps — point out the **price** next to each and the
   **★ Certified** vs **AI estimate** badges (this is your trust story)
4. Tap "Swap and save the planet" 🎉

## Next steps (post-pitch roadmap)

- [ ] Import the real EPA Safer Choice product list into `certified_products`
- [ ] Cache AI estimates in the `ai_estimates` table (schema is ready)
- [ ] Build the actual Chrome extension (JS) calling the same backend
- [ ] Add product image analysis (send image URL to the vision model)
- [ ] Track swap conversions — your key success metric
