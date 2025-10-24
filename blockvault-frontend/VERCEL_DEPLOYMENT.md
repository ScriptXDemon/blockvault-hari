# BlockVault Frontend - Vercel Deployment Guide

## 🚀 Quick Deploy to Vercel (Free)

### Method 1: Deploy via Vercel Dashboard (Recommended)

1. **Go to [vercel.com](https://vercel.com)**
2. **Sign up/Login** with GitHub, GitLab, or Bitbucket
3. **Click "New Project"**
4. **Import your repository** (upload the `blockvault-frontend` folder)
5. **Configure settings:**
   - Framework Preset: `Create React App`
   - Root Directory: `./` (or leave empty)
   - Build Command: `npm run build`
   - Output Directory: `build`
6. **Add Environment Variable:**
   - Key: `REACT_APP_API_BASE`
   - Value: `https://your-hf-space.hf.space` (your Hugging Face backend URL)
7. **Click "Deploy"**

### Method 2: Deploy via Vercel CLI

1. **Install Vercel CLI:**
   ```bash
   npm i -g vercel
   ```

2. **Navigate to frontend directory:**
   ```bash
   cd blockvault-frontend
   ```

3. **Login to Vercel:**
   ```bash
   vercel login
   ```

4. **Deploy:**
   ```bash
   vercel
   ```

5. **Set environment variable:**
   ```bash
   vercel env add REACT_APP_API_BASE
   # Enter: https://your-hf-space.hf.space
   ```

6. **Redeploy with environment variable:**
   ```bash
   vercel --prod
   ```

### Method 3: Deploy via GitHub Integration

1. **Push your code to GitHub**
2. **Connect Vercel to your GitHub repository**
3. **Vercel will automatically detect it's a React app**
4. **Set environment variables in Vercel dashboard**
5. **Deploy automatically on every push**

## ⚙️ Environment Variables

Set these in your Vercel project settings:

| Variable | Value | Description |
|----------|-------|-------------|
| `REACT_APP_API_BASE` | `https://your-hf-space.hf.space` | Backend API URL |

## 🔧 Build Configuration

Vercel will automatically:
- Install dependencies with `npm install`
- Build the app with `npm run build`
- Serve static files from `build/` directory
- Handle routing for React Router

## 📱 Custom Domain (Optional)

1. **Go to Project Settings > Domains**
2. **Add your custom domain**
3. **Update DNS records** as instructed
4. **SSL certificate** is automatically provided

## 🔄 Automatic Deployments

- **Every push to main branch** triggers automatic deployment
- **Preview deployments** for pull requests
- **Instant rollbacks** to previous versions

## 💰 Free Tier Limits

- **100GB bandwidth** per month
- **Unlimited deployments**
- **Custom domains** supported
- **Automatic HTTPS**
- **Global CDN**

## 🐛 Troubleshooting

### Build Fails
- Check `package.json` scripts
- Ensure all dependencies are listed
- Check for TypeScript errors

### API Connection Issues
- Verify `REACT_APP_API_BASE` environment variable
- Check CORS settings on backend
- Ensure backend is deployed and accessible

### Routing Issues
- Verify `vercel.json` configuration
- Check React Router setup
- Ensure all routes redirect to `index.html`

## 📞 Support

- **Vercel Documentation**: [vercel.com/docs](https://vercel.com/docs)
- **Community**: [github.com/vercel/vercel/discussions](https://github.com/vercel/vercel/discussions)
