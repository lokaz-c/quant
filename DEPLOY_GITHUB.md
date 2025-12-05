# Deploy to GitHub & Live Hosting

This guide shows you how to deploy your Quant Portfolio Simulator to the web.

## Option 1: Deploy to Render (Recommended - FREE)

Render provides free hosting for web applications with automatic deployments from GitHub.

### Steps:

1. **Push your code to GitHub** (if not already done):
   ```bash
   git add .
   git commit -m "Add deployment configuration"
   git push origin main
   ```

2. **Sign up at [Render](https://render.com)** using your GitHub account

3. **Create a New Web Service**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repository `lokaz-c/quant`
   - Configure the service:
     - **Name**: `quant-portfolio-simulator`
     - **Environment**: Python 3
     - **Build Command**: `pip install -r requirements.txt && python init_db.py`
     - **Start Command**: `gunicorn app.main:app`
     - **Instance Type**: Free

4. **Click "Create Web Service"**

5. **Wait 2-3 minutes** for deployment to complete

6. **Your app will be live at**: `https://quant-portfolio-simulator.onrender.com`

### Important Notes:
- Free tier spins down after 15 minutes of inactivity
- First request after inactivity takes ~30 seconds to wake up
- SQLite database resets on each deployment (use PostgreSQL for persistence)

---

## Option 2: Deploy to Railway (Alternative FREE option)

Railway is another excellent free hosting platform with better database persistence.

### Steps:

1. **Sign up at [Railway](https://railway.app)** with GitHub

2. **Create New Project**:
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose `lokaz-c/quant`

3. **Railway will auto-detect** the configuration from `Procfile`

4. **Add Environment Variables** (optional):
   - `DATABASE_URL` for PostgreSQL (if you want persistent data)

5. **Deploy** - Railway will automatically build and deploy

6. **Get your live URL** from the Railway dashboard

---

## Option 3: Deploy to Heroku

Heroku is a mature platform but requires a credit card even for free tier.

### Steps:

1. **Install Heroku CLI**:
   ```bash
   brew install heroku/brew/heroku  # macOS
   # or download from https://devcenter.heroku.com/articles/heroku-cli
   ```

2. **Login and Create App**:
   ```bash
   heroku login
   heroku create quant-portfolio-simulator
   ```

3. **Deploy**:
   ```bash
   git push heroku main
   ```

4. **Initialize Database**:
   ```bash
   heroku run python init_db.py
   ```

5. **Open your app**:
   ```bash
   heroku open
   ```

---

## GitHub Pages (Static Site Only)

**Note**: GitHub Pages only hosts static HTML/CSS/JS. Since this app requires a Python backend, you'll need to:

1. Deploy the backend to Render/Railway
2. Update the frontend to point to your deployed API
3. Host just the HTML on GitHub Pages

This is NOT recommended for this project since it requires API functionality.

---

## Recommended Setup for Production

For a production-ready deployment:

1. **Use Render or Railway** for hosting
2. **Add PostgreSQL database**:
   - Render: Add a PostgreSQL service in dashboard
   - Railway: Add PostgreSQL from plugins
3. **Update `DATABASE_URL`** environment variable to PostgreSQL connection string
4. **Enable HTTPS** (automatic on Render/Railway)
5. **Set up custom domain** (optional)

---

## Testing Your Deployment

Once deployed, test your live site:

1. Visit your deployment URL
2. Select a strategy and risk configuration
3. Click "Run Backtest"
4. Verify results appear

---

## Troubleshooting

**App won't start**:
- Check build logs in Render/Railway dashboard
- Ensure `requirements.txt` has all dependencies
- Verify `Procfile` is in root directory

**Database errors**:
- SQLite doesn't persist on free tiers
- Use PostgreSQL for production
- Run `init_db.py` after each deployment

**Slow initial load**:
- Free tiers sleep after inactivity
- First request wakes up the server (30 seconds)
- Consider upgrading to paid tier for 24/7 uptime

---

## Next Steps

After deployment:
- Add your live URL to the README
- Set up monitoring (Render/Railway provide basic monitoring)
- Consider adding authentication for multiple users
- Implement rate limiting for API endpoints
