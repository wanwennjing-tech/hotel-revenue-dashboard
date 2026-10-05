
import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import date, timedelta

st.set_page_config(page_title="Hotel Revenue Dashboard", page_icon="📈", layout="wide")
st.title("Hotel Revenue Dashboard")
st.caption("HMS + OTA extranet · automatic source recognition · Pre/Post strategy measurement")

# ---------- helpers ----------
def clean_money(s):
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(s.astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")

def dates(s, utc=False):
    return pd.to_datetime(s, errors="coerce", dayfirst=True, utc=utc)

def first_col(df, names):
    low = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None

def source_name(filename, df):
    fn = filename.lower()
    cols = {str(c).strip().lower() for c in df.columns}
    if "traveller's name" in cols and "channel booking id" in cols and "gross amount" in cols:
        return "ZUZU HMS"
    if "bookingidexternal_reference_id" in cols and "total_inclusive_rate" in cols:
        return "Agoda"
    if "reservation id" in cols and "booking amount" in cols and "confirmation #" in cols:
        return "Expedia"
    if "trip" in fn:
        return "Trip.com"
    if "booking.com" in fn or "bookingcom" in fn:
        return "Booking.com"
    return "Unknown"

def load_file(f):
    fn=f.name.lower()
    if fn.endswith(".csv"):
        return pd.read_csv(f)
    # HMS has 3 report rows above the actual header
    if fn.endswith((".xlsx",".xls")):
        probe = pd.read_excel(f, header=None, nrows=8)
        header_row = None
        for i,row in probe.iterrows():
            vals = [str(x).strip().lower() for x in row.tolist()]
            if "channel booking id" in vals or "reservation id" in vals or "order id" in vals:
                header_row=i; break
        return pd.read_excel(f, header=header_row if header_row is not None else 0)
    raise ValueError("Unsupported file type")

def base_frame(n):
    return pd.DataFrame(index=range(n), columns=[
        "Property","Source Type","Channel","Reservation ID","Booking Date","Check-in Date",
        "Check-out Date","Rooms","Nights","Room Nights","Revenue","Status","Room Type","Rate Plan","Source File"
    ])

def parse_hms(df, filename, prop):
    o=base_frame(len(df))
    o["Property"]=prop
    o["Source Type"]="HMS"
    o["Channel"]=df.get("Channel","HMS")
    o["Reservation ID"]=df.get("Channel booking ID")
    o["Booking Date"]=dates(df.get("Booked on (UTC)"), utc=True).dt.tz_convert("Asia/Manila").dt.tz_localize(None)
    o["Check-in Date"]=dates(df.get("Arrival date"))
    o["Check-out Date"]=dates(df.get("Departure date"))
    o["Rooms"]=1
    o["Nights"]=pd.to_numeric(df.get("Nights"),errors="coerce")
    o["Room Nights"]=o["Nights"] # each HMS row is one booked room/room-id line
    o["Revenue"]=clean_money(df.get("Gross Amount"))
    o["Status"]=df.get("Booking status")
    o["Room Type"]=df.get("Room type")
    o["Rate Plan"]=df.get("Rate plan")
    o["Source File"]=filename
    return o

def parse_agoda(df, filename, prop):
    o=base_frame(len(df))
    o["Property"]=prop; o["Source Type"]="OTA Extranet"; o["Channel"]="Agoda"
    o["Reservation ID"]=df.get("BookingIDExternal_reference_ID")
    o["Booking Date"]=dates(df.get("BookedDate"))
    o["Check-in Date"]=dates(df.get("StayDateFrom"))
    o["Check-out Date"]=dates(df.get("StayDateTo"))
    nights=pd.to_numeric(df.get("No_of_night"),errors="coerce")
    # Agoda exports supplied by the user sometimes contain 0 in No_of_room.
    # Do not turn 0 into zero production; default to one booked room unless positive room count exists.
    rooms=pd.to_numeric(df.get("No_of_room"),errors="coerce")
    rooms=rooms.where(rooms>0,1)
    o["Rooms"]=rooms; o["Nights"]=nights; o["Room Nights"]=rooms*nights
    o["Revenue"]=clean_money(df.get("Total_inclusive_rate"))
    o["Status"]=df.get("Status"); o["Room Type"]=df.get("RoomType"); o["Rate Plan"]=df.get("RatePlan")
    o["Source File"]=filename
    return o

def parse_expedia(df, filename, prop):
    o=base_frame(len(df))
    o["Property"]=prop; o["Source Type"]="OTA Extranet"; o["Channel"]="Expedia"
    o["Reservation ID"]=df.get("Reservation ID")
    b=pd.to_datetime(df.get("Booked"),errors="coerce",utc=True)
    o["Booking Date"]=b.dt.tz_convert("Asia/Manila").dt.tz_localize(None)
    o["Check-in Date"]=dates(df.get("Check-in")); o["Check-out Date"]=dates(df.get("Check-out"))
    o["Rooms"]=1
    o["Nights"]=(o["Check-out Date"]-o["Check-in Date"]).dt.days
    o["Room Nights"]=o["Nights"]
    o["Revenue"]=clean_money(df.get("Booking amount"))
    o["Status"]=df.get("Status"); o["Room Type"]=df.get("Room"); o["Rate Plan"]=df.get("Payment type")
    o["Source File"]=filename
    return o

def generic_parser(df, filename, prop, source):
    # Flexible fallback for Trip.com / Booking.com and new formats.
    o=base_frame(len(df))
    o["Property"]=prop; o["Source Type"]="OTA Extranet"; o["Channel"]=source
    cmap = {
        "Reservation ID":["reservation id","booking id","order id","reservation number","confirmation number"],
        "Booking Date":["booking date","booked date","booked on","reservation date","create time","booking time"],
        "Check-in Date":["check-in","check in","check-in date","arrival","arrival date"],
        "Check-out Date":["check-out","check out","check-out date","departure","departure date"],
        "Rooms":["rooms","no. of rooms","number of rooms","room count"],
        "Nights":["nights","no. of nights","length of stay"],
        "Revenue":["revenue","booking amount","total price","total amount","amount","price","commissionable amount"],
        "Status":["status","booking status","reservation status","order status"],
        "Room Type":["room type","room","room name"],
        "Rate Plan":["rate plan","rate name","meal plan"]
    }
    for target,names in cmap.items():
        c=first_col(df,names)
        if c is not None: o[target]=df[c]
    for c in ["Booking Date","Check-in Date","Check-out Date"]: o[c]=dates(o[c])
    for c in ["Rooms","Nights"]: o[c]=pd.to_numeric(o[c],errors="coerce")
    o["Rooms"]=o["Rooms"].where(o["Rooms"]>0,1).fillna(1)
    missing_n=o["Nights"].isna()
    o.loc[missing_n,"Nights"]=(o.loc[missing_n,"Check-out Date"]-o.loc[missing_n,"Check-in Date"]).dt.days
    o["Room Nights"]=o["Rooms"]*o["Nights"]
    o["Revenue"]=clean_money(o["Revenue"])
    o["Source File"]=filename
    return o

def valid(df):
    s=df["Status"].fillna("").astype(str).str.lower()
    return df[~s.str.contains("cancel|no.?show|void",regex=True)].copy()

def allocate_stays(df,start,end):
    out=[]
    start=pd.Timestamp(start); end=pd.Timestamp(end)+pd.Timedelta(days=1)
    for _,r in df.iterrows():
        ci,co=r["Check-in Date"],r["Check-out Date"]
        if pd.isna(ci) or pd.isna(co) or co<=ci: continue
        a=max(ci.normalize(),start); b=min(co.normalize(),end)
        n=max(0,(b-a).days)
        if not n: continue
        total_n=max(float(r["Nights"] or 1),1)
        total_rn=float(r["Room Nights"] or total_n)
        arn=n*(total_rn/total_n)
        rev=float(r["Revenue"] or 0)
        rr=r.copy(); rr["_RN"]=arn; rr["_REV"]=rev*(arn/total_rn) if total_rn else 0
        out.append(rr)
    return pd.DataFrame(out)

def period(df,basis,start,end):
    nd=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
    if basis=="Booking date":
        z=df[(df["Booking Date"]>=pd.Timestamp(start))&(df["Booking Date"]<pd.Timestamp(end)+pd.Timedelta(days=1))].copy()
        rn=z["Room Nights"].sum(); rev=z["Revenue"].sum(); bk=z["Reservation ID"].nunique()
    else:
        z=allocate_stays(df,start,end)
        rn=z["_RN"].sum() if len(z) else 0; rev=z["_REV"].sum() if len(z) else 0
        bk=z["Reservation ID"].nunique() if len(z) else 0
    return dict(days=nd,bookings=bk,rn=rn,rev=rev,bpd=bk/nd,rnpd=rn/nd,revpd=rev/nd,adr=rev/rn if rn else 0)

def change(a,b): return (b/a-1)*100 if a else np.nan

# ---------- data intake ----------
if "reservations" not in st.session_state:
    st.session_state.reservations=pd.DataFrame()

with st.sidebar:
    st.header("Upload reservation files")
    prop=st.text_input("Property", placeholder="e.g. Summit Ridge Tagaytay")
    files=st.file_uploader("HMS / Agoda / Expedia / Trip.com / Booking.com", type=["xlsx","xls","csv"], accept_multiple_files=True)
    if st.button("Import files", type="primary", disabled=not files or not prop):
        imported=[]; messages=[]
        for f in files:
            try:
                raw=load_file(f); src=source_name(f.name,raw)
                if src=="ZUZU HMS": z=parse_hms(raw,f.name,prop)
                elif src=="Agoda": z=parse_agoda(raw,f.name,prop)
                elif src=="Expedia": z=parse_expedia(raw,f.name,prop)
                else: z=generic_parser(raw,f.name,prop,src)
                imported.append(z); messages.append(f"✓ {f.name}: {src}, {len(z):,} rows")
            except Exception as e:
                messages.append(f"✗ {f.name}: {e}")
        if imported:
            new=pd.concat(imported,ignore_index=True)
            st.session_state.reservations=pd.concat([st.session_state.reservations,new],ignore_index=True)
        for m in messages: st.write(m)

    if not st.session_state.reservations.empty and st.button("Clear all uploaded data"):
        st.session_state.reservations=pd.DataFrame(); st.rerun()

df=st.session_state.reservations.copy()
if df.empty:
    st.info("Start by entering a property name and uploading one or more reservation exports in the left panel.")
    st.markdown("**Recognised automatically:** ZUZU HMS, Agoda and Expedia. Trip.com and Booking.com use a flexible importer in this version.")
    st.stop()

df=valid(df)
df["Unique Key"]=df["Property"].astype(str)+"|"+df["Source Type"].astype(str)+"|"+df["Channel"].astype(str)+"|"+df["Reservation ID"].astype(str)
df=df.drop_duplicates("Unique Key",keep="last")

st.subheader("Loaded data")
c1,c2,c3,c4=st.columns(4)
c1.metric("Reservations",f"{df['Reservation ID'].nunique():,}")
c2.metric("Room nights",f"{df['Room Nights'].sum():,.0f}")
c3.metric("Revenue",f"{df['Revenue'].sum():,.0f}")
c4.metric("Files",df["Source File"].nunique())

st.caption("HMS and OTA extranet data remain separate. The dashboard does not add them together as one production total.")

# ---------- analysis ----------
st.subheader("Pre / Post strategy analysis")
a,b,c,d=st.columns(4)
property_sel=a.selectbox("Property",sorted(df["Property"].dropna().unique()))
source_sel=b.selectbox("Data source",["HMS","OTA Extranet"])
basis=c.selectbox("Basis",["Booking date","Stay date"])
impl=d.date_input("Implementation date",date.today())

e,f,g=st.columns(3)
strategy=e.text_input("Strategy / action",placeholder="e.g. DOW rate increase")
pre_days=int(f.number_input("Pre days",1,365,7))
post_days=int(g.number_input("Post days",1,365,7))
exclude=st.checkbox("Exclude implementation date",True)

x=df[(df["Property"]==property_sel)&(df["Source Type"]==source_sel)].copy()
pre_end=impl-timedelta(days=1); pre_start=pre_end-timedelta(days=pre_days-1)
post_start=impl+timedelta(days=1) if exclude else impl; post_end=post_start+timedelta(days=post_days-1)
st.caption(f"Pre: {pre_start:%d %b %Y}–{pre_end:%d %b %Y} · Post: {post_start:%d %b %Y}–{post_end:%d %b %Y}")

if x.empty:
    st.warning("No data for this source.")
    st.stop()

P=period(x,basis,pre_start,pre_end); Q=period(x,basis,post_start,post_end)
metrics=[
    ("Bookings / day",P["bpd"],Q["bpd"]),
    ("Room nights / day",P["rnpd"],Q["rnpd"]),
    ("Revenue / day",P["revpd"],Q["revpd"]),
    ("ADR",P["adr"],Q["adr"])
]
tbl=pd.DataFrame(metrics,columns=["Metric","Pre","Post"])
tbl["Change %"]=[change(a,b) for _,a,b in metrics]
st.dataframe(tbl.style.format({"Pre":"{:,.1f}","Post":"{:,.1f}","Change %":"{:+.1f}%"}),hide_index=True,use_container_width=True)

k1,k2,k3,k4=st.columns(4)
for box,(label,a,b) in zip([k1,k2,k3,k4],metrics):
    box.metric(label,f"{b:,.1f}",f"{change(a,b):+.1f}%")

# DOW pickup by stay/check-in day for booking-date production
st.subheader("Day-of-week pickup")
if basis=="Booking date":
    def dow(start,end):
        z=x[(x["Booking Date"]>=pd.Timestamp(start))&(x["Booking Date"]<pd.Timestamp(end)+pd.Timedelta(days=1))].copy()
        z["DOW"]=z["Check-in Date"].dt.day_name()
        order=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        g=z.groupby("DOW").agg(Bookings=("Reservation ID","nunique"),RN=("Room Nights","sum"),Revenue=("Revenue","sum")).reindex(order).fillna(0)
        g["ADR"]=np.where(g["RN"]>0,g["Revenue"]/g["RN"],0)
        return g
    A=dow(pre_start,pre_end); B=dow(post_start,post_end)
    out=pd.DataFrame({"DOW":A.index,
        "Pre RN/day":A.RN.values/pre_days,"Post RN/day":B.RN.values/post_days,
        "RN Δ%":[change(a,b) for a,b in zip(A.RN/pre_days,B.RN/post_days)],
        "Pre Revenue/day":A.Revenue.values/pre_days,"Post Revenue/day":B.Revenue.values/post_days,
        "Revenue Δ%":[change(a,b) for a,b in zip(A.Revenue/pre_days,B.Revenue/post_days)],
        "Pre ADR":A.ADR.values,"Post ADR":B.ADR.values,
        "ADR Δ%":[change(a,b) for a,b in zip(A.ADR,B.ADR)]})
    st.dataframe(out.style.format({"Pre RN/day":"{:,.1f}","Post RN/day":"{:,.1f}","RN Δ%":"{:+.1f}%",
        "Pre Revenue/day":"{:,.0f}","Post Revenue/day":"{:,.0f}","Revenue Δ%":"{:+.1f}%",
        "Pre ADR":"{:,.0f}","Post ADR":"{:,.0f}","ADR Δ%":"{:+.1f}%"}),hide_index=True,use_container_width=True)
else:
    st.info("Stay-date DOW allocation will be added after the core source parsers are fully validated.")

st.subheader("Production breakdown")
tab1,tab2,tab3=st.tabs(["Channel","Room type","Rate plan"])
for tab,col in [(tab1,"Channel"),(tab2,"Room Type"),(tab3,"Rate Plan")]:
    with tab:
        q=x.copy(); q[col]=q[col].fillna("Unknown").astype(str)
        g=q.groupby(col).agg(Bookings=("Reservation ID","nunique"),RN=("Room Nights","sum"),Revenue=("Revenue","sum")).reset_index()
        g["ADR"]=np.where(g.RN>0,g.Revenue/g.RN,0)
        st.dataframe(g.sort_values("Revenue",ascending=False).style.format({"RN":"{:,.0f}","Revenue":"{:,.0f}","ADR":"{:,.0f}"}),hide_index=True,use_container_width=True)

st.subheader("Export")
st.download_button("Download standardised reservations CSV",df.to_csv(index=False).encode("utf-8"),
                   "standardised_reservations.csv","text/csv")
st.download_button("Download Pre/Post summary CSV",tbl.to_csv(index=False).encode("utf-8"),
                   "pre_post_summary.csv","text/csv")

with st.expander("Current data rules"):
    st.markdown("""
- **ZUZU HMS:** report header is detected automatically; each HMS row is treated as one room line. `Booked on (UTC)` is converted to Manila/Singapore time for booking-date analysis.
- **Agoda:** `Total_inclusive_rate` is revenue. Because the supplied Agoda export can show `No_of_room = 0`, zero is not treated as zero production; it defaults to one room unless a positive room count is supplied.
- **Expedia:** booking timestamp is converted from its timezone to Manila/Singapore time; `Booking amount` is revenue.
- Cancelled, no-show and void records are excluded when status identifies them.
- HMS and OTA extranet datasets are never summed together automatically, avoiding double counting.
- Stay-date analysis allocates revenue proportionally to room nights falling inside the selected period.
""")
