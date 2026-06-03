# Affinity Order Detail Analytics

A Streamlit web application for Affinity Group sales analytics with:
- Role-based access control (territory/department/full)
- Natural language data querying via Snowflake Cortex AI
- Auto-generated charts
- Email results capability via Microsoft Graph API

## Setup

1. Deploy to Streamlit Community Cloud
2. Add Snowflake secrets in app settings
3. Users log in with their @affinitysales.com email

## Access Tiers

| Tier | Who | Access |
|------|-----|--------|
| Full | President/CEO/ACP dept | All data |
| Department | VP/Director | All territories in their department |
| Territory | Everyone else | Data matching their OFFICE_LOCATION |
