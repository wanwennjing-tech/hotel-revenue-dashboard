# Hotel Revenue Dashboard

Deployment-ready Streamlit dashboard for HMS + OTA reservation analysis.

## Deploy on Streamlit Community Cloud
1. Upload `app.py` and `requirements.txt` to your GitHub repository.
2. In Streamlit Community Cloud choose **Create app**.
3. Select your GitHub repository and branch `main`.
4. Main file path: `app.py`
5. Deploy.

## Current automatic parsers
- ZUZU HMS reservation export
- Agoda reservation export
- Expedia reservation export
- Flexible fallback for Trip.com / Booking.com `.xls` files

`xlrd` is included so legacy `.xls` files can be read after deployment.

## Data design
HMS and OTA extranet data are kept separate to prevent double counting. Use the Data Source selector to analyse either dataset.
