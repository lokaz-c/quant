# Deployment Guide

Deploy your Quant Portfolio Simulator to production cloud platforms.

## Option 1: Render.com (Easiest - FREE)

**Best for**: Quick deployment, free tier available

### Steps:

1. **Create account** at [render.com](https://render.com)

2. **Create PostgreSQL database**:
   - Click "New +" → "PostgreSQL"
   - Name: `quant-db`
   - Database: `quant_db`
   - User: `quant_user`
   - Region: Choose closest to you
   - Instance Type: Free tier
   - Click "Create Database"
   - Copy the "Internal Database URL"

3. **Create Web Service**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repo: `lokaz-c/quant`
   - Name: `quant-portfolio-simulator`
   - Environment: Docker
   - Region: Same as database
   - Instance Type: Free tier
   - Add Environment Variable:
     - Key: `DATABASE_URL`
     - Value: [paste Internal Database URL from step 2]
   - Click "Create Web Service"

4. **Wait for deployment** (5-10 minutes)

5. **Access your app** at: `https://quant-portfolio-simulator.onrender.com`

**Note**: Free tier sleeps after inactivity. First request may take 30 seconds.

---

## Option 2: Railway.app (Easy - FREE)

**Best for**: Simple deployment with database included

### Steps:

1. **Create account** at [railway.app](https://railway.app)

2. **New Project from GitHub**:
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose `lokaz-c/quant`

3. **Add PostgreSQL**:
   - Click "+ New"
   - Select "Database" → "Add PostgreSQL"

4. **Configure Web Service**:
   - Click on your web service
   - Settings → Environment
   - Add variable:
     - `DATABASE_URL`: `${{Postgres.DATABASE_URL}}`
   - Settings → Networking
   - Click "Generate Domain"

5. **Deploy**:
   - Railway auto-deploys on push
   - Access at generated domain

**Cost**: $5/month after free trial (500 hours free)

---

## Option 3: Heroku (Popular - PAID)

**Best for**: Production apps, established platform

### Steps:

1. **Install Heroku CLI**:
```bash
brew tap heroku/brew && brew install heroku
# or
curl https://cli-assets.heroku.com/install.sh | sh
```

2. **Login**:
```bash
heroku login
```

3. **Create app**:
```bash
heroku create quant-portfolio-sim
```

4. **Add PostgreSQL**:
```bash
heroku addons:create heroku-postgresql:mini
```

5. **Configure**:
```bash
heroku config:set FLASK_ENV=production
```

6. **Deploy**:
```bash
git push heroku main
```

7. **Initialize database**:
```bash
heroku run python -c "from app.models.database import init_db; init_db()"
heroku run python backtest_engine/data_loader.py
```

8. **Open app**:
```bash
heroku open
```

**Cost**: ~$7/month for Eco dynos

---

## Option 4: DigitalOcean App Platform

**Best for**: More control, scalable

### Steps:

1. **Create account** at [digitalocean.com](https://digitalocean.com)

2. **Create App**:
   - Click "Create" → "Apps"
   - Connect GitHub: `lokaz-c/quant`
   - Select branch: `main`
   - Autodeploy: Yes

3. **Add Database**:
   - Click "Add Resource" → "Database"
   - Type: PostgreSQL
   - Plan: Basic ($15/month)

4. **Configure**:
   - Environment Variables:
     - `DATABASE_URL`: `${db.DATABASE_URL}`

5. **Deploy**:
   - Click "Create Resources"
   - Wait for deployment

**Cost**: ~$5-15/month

---

## Option 5: AWS (Most Powerful - COMPLEX)

**Best for**: Enterprise scale, full control

### Quick Setup with ECS + RDS:

1. **Install AWS CLI**:
```bash
brew install awscli
aws configure
```

2. **Use provided CloudFormation template** (see `aws-deploy.yml`)

3. **Deploy**:
```bash
aws cloudformation create-stack \
  --stack-name quant-portfolio \
  --template-body file://aws-deploy.yml \
  --parameters ParameterKey=GitHubRepo,ParameterValue=lokaz-c/quant
```

**Cost**: ~$20-50/month depending on usage

---

## Option 6: Google Cloud Run (Serverless)

**Best for**: Pay-per-use, auto-scaling

### Steps:

1. **Install gcloud CLI**:
```bash
brew install google-cloud-sdk
gcloud init
```

2. **Enable services**:
```bash
gcloud services enable run.googleapis.com
gcloud services enable sqladmin.googleapis.com
```

3. **Create Cloud SQL (PostgreSQL)**:
```bash
gcloud sql instances create quant-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1
```

4. **Build and deploy**:
```bash
gcloud run deploy quant-portfolio \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars DATABASE_URL=postgresql://...
```

**Cost**: Pay per request (very cheap for low traffic)

---

## Recommended: Start with Render.com

For your portfolio project, I recommend **Render.com** because:
- ✅ Completely free tier
- ✅ Automatic HTTPS
- ✅ Easy GitHub integration
- ✅ Auto-deploys on push
- ✅ Built-in PostgreSQL
- ✅ No credit card required

---

## Pre-Deployment Checklist

Before going live, update these files:

### 1. Update `.env.example` → Create `.env`
```bash
DATABASE_URL=<your-production-database-url>
FLASK_ENV=production
SECRET_KEY=<generate-strong-secret-key>
```

### 2. Generate Secret Key
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Security Updates

Add to `app/main.py`:
```python
# Add security headers
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response
```

---

## Post-Deployment

After deployment:

1. **Generate sample data**:
```bash
# If on Render/Railway/Heroku:
# SSH into container or use their CLI to run:
python backtest_engine/data_loader.py
```

2. **Run migrations**:
```bash
python -c "from app.models.database import init_db; init_db()"
```

3. **Test the API**:
```bash
curl https://your-app-url.com/health
curl https://your-app-url.com/api/strategies/
```

4. **Monitor logs**:
   - Most platforms have built-in log viewers
   - Check for any errors

---

## Custom Domain (Optional)

Once deployed, you can add a custom domain:

1. **Buy domain** (Namecheap, Google Domains, etc.)
2. **Add CNAME record**:
   - Name: `quant` (or `www`)
   - Value: Your platform's URL
3. **Configure in platform**:
   - Render: Settings → Custom Domain
   - Railway: Settings → Domains
   - Heroku: `heroku domains:add quant.yourdomain.com`

---

## Monitoring & Scaling

### Free Monitoring Tools:
- **UptimeRobot**: Check if site is up
- **Sentry**: Error tracking (free tier)
- **LogRocket**: User session replay
- **Google Analytics**: Usage tracking

### When to Scale:
- More than 100 concurrent users → Upgrade tier
- Database > 1GB → Separate DB instance
- API response > 2s → Add caching (Redis)

---

## Next Steps After Live

1. **Add to Resume**:
   - "Deployed production trading platform serving X users"
   - Include live URL

2. **LinkedIn Post**:
   - Share live link
   - Demo video/GIF
   - Technical breakdown

3. **Monitor Usage**:
   - Track API calls
   - Monitor performance
   - Gather user feedback

4. **Iterate**:
   - Add features based on feedback
   - Improve performance
   - Add more strategies

---

## Troubleshooting

### App won't start:
```bash
# Check logs on your platform
# Common issues:
# 1. DATABASE_URL not set
# 2. Port not bound correctly (use PORT env var)
# 3. Missing dependencies in requirements.txt
```

### Database connection failed:
```bash
# Verify DATABASE_URL format:
postgresql://user:password@host:port/database

# Test connection:
python -c "from app.models.database import engine; print(engine.connect())"
```

### Out of memory:
```bash
# Reduce dataset size or upgrade tier
# Or implement pagination for large queries
```

---

## Cost Comparison

| Platform | Free Tier | Paid Tier | Best For |
|----------|-----------|-----------|----------|
| Render | ✅ Yes | $7/month | Portfolios |
| Railway | 500hrs free | $5/month | Simple apps |
| Heroku | ❌ No | $7/month | Production |
| DigitalOcean | ❌ No | $15/month | Scalability |
| AWS | 12mo free | $20+/month | Enterprise |
| Google Cloud | $300 credit | Pay-per-use | Serverless |

---

Ready to deploy? Start with Render.com for free! 🚀
