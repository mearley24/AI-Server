# Cline Prompt: Add Google Analytics, Ads Conversion Tracking, and Search Console

**Repo:** `mearley24/symphonysh` (React + Vite + Tailwind, Cloudflare Pages)
**Goal:** Wire up Google Analytics 4, Google Ads conversion tracking, and Google Search Console verification so Matt can measure ad ROI and organic SEO performance. Commit and push when done.

---

## IMPORTANT
- Test `npm run build` after changes to ensure zero errors
- All tracking scripts go in `index.html` in the `<head>` section
- Do NOT break any existing functionality
- The GA4 Measurement ID and Google Ads Conversion ID will use environment variables or placeholder values that Matt fills in

---

## 1. GOOGLE ANALYTICS 4 (GA4)

Add the GA4 gtag.js snippet to `index.html` in the `<head>`, BEFORE the existing scripts:

```html
<!-- Google Analytics 4 -->
<script async src="https://www.googletagmanager.com/gtag/js?id=GA_MEASUREMENT_ID"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'GA_MEASUREMENT_ID');
</script>
```

Replace `GA_MEASUREMENT_ID` with a placeholder comment so Matt can swap it:
```
<!-- REPLACE GA_MEASUREMENT_ID with your GA4 Measurement ID (format: G-XXXXXXXXXX) -->
<!-- Get it from: Google Analytics > Admin > Data Streams > Web > Measurement ID -->
```

---

## 2. GOOGLE ADS CONVERSION TRACKING

Add the Google Ads global site tag right after the GA4 snippet:

```html
<!-- Google Ads -->
<script async src="https://www.googletagmanager.com/gtag/js?id=ADS_CONVERSION_ID"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('config', 'ADS_CONVERSION_ID');
</script>
```

Replace `ADS_CONVERSION_ID` with a placeholder comment:
```
<!-- REPLACE ADS_CONVERSION_ID with your Google Ads Conversion ID (format: AW-XXXXXXXXXX) -->
<!-- Get it from: Google Ads > Tools > Conversions > your conversion action > Tag setup -->
```

**IMPORTANT:** Since both GA4 and Ads use gtag.js, they can share one loader. Combine them:

```html
<!-- Google Analytics 4 + Google Ads Tracking -->
<!-- SETUP: Replace GA_MEASUREMENT_ID with your GA4 ID (G-XXXXXXXXXX) -->
<!-- SETUP: Replace ADS_CONVERSION_ID with your Google Ads ID (AW-XXXXXXXXXX) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=GA_MEASUREMENT_ID"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'GA_MEASUREMENT_ID');
  gtag('config', 'ADS_CONVERSION_ID');
</script>
```

### Track conversions on key actions:

**a) Scheduling form submission** — In `src/pages/scheduling/components/confirmation/ZapierNotifier.tsx` or wherever the scheduling form success callback is, add:

```typescript
// Fire Google Ads conversion on successful booking
if (typeof window.gtag === 'function') {
  window.gtag('event', 'conversion', {
    'send_to': 'ADS_CONVERSION_ID/CONVERSION_LABEL',
    'value': 1.0,
    'currency': 'USD'
  });
}
```

Add a placeholder comment: `// SETUP: Replace ADS_CONVERSION_ID/CONVERSION_LABEL with your conversion label from Google Ads`

**b) Phone call clicks** — Track when someone taps the phone number. In the hero section of `Index.tsx` and anywhere `tel:+19705193013` appears, add an onClick handler:

```typescript
onClick={() => {
  if (typeof window.gtag === 'function') {
    window.gtag('event', 'conversion', {
      'send_to': 'ADS_CONVERSION_ID/PHONE_CONVERSION_LABEL',
    });
  }
}}
```

Since phone links appear in multiple components (Index.tsx, Header.tsx, Footer.tsx, About.tsx, Contact.tsx, CityPage.tsx), create a utility function:

Create `src/utils/tracking.ts`:
```typescript
declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
    dataLayer?: unknown[];
  }
}

export function trackPhoneClick() {
  if (typeof window.gtag === 'function') {
    window.gtag('event', 'conversion', {
      // SETUP: Replace with your phone conversion label from Google Ads
      'send_to': 'ADS_CONVERSION_ID/PHONE_CONVERSION_LABEL',
    });
    window.gtag('event', 'phone_click', {
      'event_category': 'engagement',
      'event_label': '(970) 519-3013',
    });
  }
}

export function trackScheduleSubmit() {
  if (typeof window.gtag === 'function') {
    window.gtag('event', 'conversion', {
      // SETUP: Replace with your schedule conversion label from Google Ads
      'send_to': 'ADS_CONVERSION_ID/SCHEDULE_CONVERSION_LABEL',
      'value': 1.0,
      'currency': 'USD',
    });
    window.gtag('event', 'schedule_submit', {
      'event_category': 'conversion',
      'event_label': 'consultation_booked',
    });
  }
}

export function trackPageView(pagePath: string, pageTitle: string) {
  if (typeof window.gtag === 'function') {
    window.gtag('event', 'page_view', {
      'page_path': pagePath,
      'page_title': pageTitle,
    });
  }
}
```

**c) Apply tracking to phone links** — Import `trackPhoneClick` and add `onClick={trackPhoneClick}` to every `<a href="tel:...">` in:
- `src/pages/Index.tsx`
- `src/components/Header.tsx`
- `src/components/Footer.tsx`
- `src/pages/About.tsx`
- `src/pages/Contact.tsx`
- `src/pages/CityPage.tsx`
- `src/components/MobileClickToCall.tsx`

**d) Apply schedule tracking** — Import `trackScheduleSubmit` and call it in the scheduling confirmation flow when a booking is successfully submitted.

---

## 3. GOOGLE SEARCH CONSOLE VERIFICATION

Add the Search Console verification meta tag to `index.html` in `<head>`:

```html
<!-- Google Search Console Verification -->
<!-- SETUP: Replace VERIFICATION_CODE with your code from Search Console > Settings > Ownership verification > HTML tag -->
<meta name="google-site-verification" content="VERIFICATION_CODE" />
```

---

## 4. SUBMIT SITEMAP TO SEARCH CONSOLE

Add a comment in `public/robots.txt` reminding to submit the sitemap:

```
# After verifying in Google Search Console, submit the sitemap:
# Go to: https://search.google.com/search-console > Sitemaps > Add "https://symphonysh.com/sitemap.xml"
```

---

## 5. REMOVE GPTENGINEER SCRIPT

In `index.html`, remove this line — it's a leftover from the Lovable/GPT Engineer build tool and shouldn't be in production:

```html
<script src="https://cdn.gpteng.co/gptengineer.js" type="module"></script>
```

Remove the surrounding comment too:
```html
<!-- IMPORTANT: DO NOT REMOVE THIS SCRIPT TAG OR THIS VERY COMMENT! -->
```

---

## 6. SETUP INSTRUCTIONS FILE

Create `GOOGLE_SETUP.md` in the repo root with instructions for Matt:

```markdown
# Google Tracking Setup — Symphony Smart Homes

## Step 1: Google Analytics 4
1. Go to https://analytics.google.com
2. Create a new GA4 property for symphonysh.com
3. Create a Web data stream
4. Copy the Measurement ID (format: G-XXXXXXXXXX)
5. In `index.html`, replace `GA_MEASUREMENT_ID` with your ID (appears twice)

## Step 2: Google Ads Conversion Tracking
1. Go to Google Ads > Goals > Conversions > New conversion action
2. Create two conversions:
   - "Schedule Consultation" (category: Submit lead form)
   - "Phone Call Click" (category: Phone call leads)
3. Copy the Conversion ID (format: AW-XXXXXXXXXX) and each Conversion Label
4. In `index.html`, replace `ADS_CONVERSION_ID` with your Conversion ID
5. In `src/utils/tracking.ts`, replace the placeholder conversion labels

## Step 3: Google Search Console
1. Go to https://search.google.com/search-console
2. Add property: https://symphonysh.com
3. Choose "HTML tag" verification method
4. Copy the verification code
5. In `index.html`, replace `VERIFICATION_CODE` with your code
6. Verify in Search Console
7. Go to Sitemaps > Add: https://symphonysh.com/sitemap.xml

## Step 4: Link Everything
1. In Google Analytics: Admin > Google Ads Linking > Link your Ads account
2. In Google Ads: Tools > Linked accounts > Google Analytics > Link your GA4 property
3. In Google Search Console: Settings > Users and permissions > Add your Google Ads email if different
```

---

## COMMIT MESSAGE
```
feat: add Google Analytics, Ads conversion tracking, Search Console verification, remove gptengineer script
```

Push to main when done. Cloudflare Pages will auto-deploy.
