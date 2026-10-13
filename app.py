import io
import subprocess
import sys
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Sales and Profit Dashboard", layout="wide")
BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "superstore.csv"
REQUIRED = ["Order ID", "Order Date", "Region", "Category", "Product Name", "Sales", "Discount", "Profit"]


@st.cache_data
def load_data(file_bytes, name):
    # 1. Read: uploaded file (csv/xlsx) or the default sample file
    if file_bytes is None:
        df = pd.read_csv(DATA)
    elif name.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv(io.BytesIO(file_bytes), encoding="latin1")
    canon = {"order id": "Order ID", "order date": "Order Date", "region": "Region", "category": "Category",
             "product name": "Product Name", "sales": "Sales", "discount": "Discount", "profit": "Profit",
             "customer id": "Customer ID", "sub category": "Sub-Category", "segment": "Segment", "quantity": "Quantity"}
    df.columns = [canon.get(c.strip().lower().replace("_", " ").replace("-", " "), c.strip()) for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return None, {"missing": missing}
    # 2. Clean: duplicates, wrong dates, nulls
    report = {"rows_raw": len(df), "duplicates": int(df.duplicated().sum())}
    df = df.drop_duplicates()
    df["Order Date"] = pd.to_datetime(df["Order Date"], errors="coerce")
    report["bad_dates"] = int(df["Order Date"].isna().sum())
    report["null_discount"] = int(df["Discount"].isna().sum())
    report["null_profit"] = int(df["Profit"].isna().sum())
    df["Discount"] = df["Discount"].fillna(0)
    df = df.dropna(subset=["Order Date", "Sales", "Profit"])
    # 3. Feature columns
    df["Month"] = df["Order Date"].dt.to_period("M").dt.to_timestamp()
    df["Profit Margin %"] = np.where(df["Sales"] != 0, df["Profit"] / df["Sales"] * 100, 0)
    report["rows_clean"] = len(df)
    return df.reset_index(drop=True), report


st.title("Sales performance and profit analysis")
up = st.sidebar.file_uploader("Upload orders file (CSV or Excel)", type=["csv", "xlsx"])
if up is None and not DATA.exists():
    st.error("data/superstore.csv not found. Upload a file in the sidebar.")
    st.stop()
df, report = load_data(up.getvalue() if up else None, up.name if up else "")
if df is None:
    st.error(f"Your file is missing these columns: {', '.join(report['missing'])}")
    st.stop()
# ---------- Filters ----------
st.sidebar.header("Filters")
regions = st.sidebar.multiselect("Region", sorted(df["Region"].unique()), default=sorted(df["Region"].unique()))
cats = st.sidebar.multiselect("Category", sorted(df["Category"].unique()), default=sorted(df["Category"].unique()))
dmin, dmax = df["Order Date"].min().date(), df["Order Date"].max().date()
dr = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
if len(dr) != 2:
    st.stop()
f = df[df["Region"].isin(regions) & df["Category"].isin(cats)
       & (df["Order Date"].dt.date >= dr[0]) & (df["Order Date"].dt.date <= dr[1])]
if f.empty:
    st.warning("No data for these filters. Change the filters.")
    st.stop()

tab1, tab2, tab3 = st.tabs(["Dashboard", "SQL queries", "Data cleaning"])

# ---------- Dashboard ----------
with tab1:
    sales, profit = f["Sales"].sum(), f["Profit"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total sales", f"${sales:,.0f}")
    c2.metric("Total profit", f"${profit:,.0f}")
    c3.metric("Profit margin", f"{profit / sales * 100:.1f}%")
    c4.metric("Orders", f"{f['Order ID'].nunique():,}")

    monthly = f.groupby("Month")[["Sales", "Profit"]].sum().reset_index()
    monthly["Sales growth %"] = monthly["Sales"].pct_change() * 100
    st.subheader("Monthly sales and profit")
    st.plotly_chart(px.line(monthly, x="Month", y=["Sales", "Profit"], labels={"value": "Amount ($)", "variable": ""}), use_container_width=True)

    cat = f.groupby("Category")[["Sales", "Profit"]].sum()
    cat["Margin %"] = (cat["Profit"] / cat["Sales"] * 100).round(1)
    cat = cat.reset_index()
    a, b = st.columns(2)
    a.subheader("Profit margin by category")
    a.plotly_chart(px.bar(cat, x="Category", y="Margin %", color="Margin %", color_continuous_scale="RdYlGn"), use_container_width=True)
    reg = f.groupby("Region")[["Sales", "Profit"]].sum().reset_index()
    b.subheader("Sales and profit by region")
    b.plotly_chart(px.bar(reg, x="Region", y=["Sales", "Profit"], barmode="group", labels={"value": "Amount ($)", "variable": ""}), use_container_width=True)

    f = f.assign(**{"Discount band": pd.cut(f["Discount"], [-0.01, 0, 0.1, 0.2, 0.3, 1.0],
                                           labels=["0%", "1-10%", "11-20%", "21-30%", "30%+"])})
    disc = f.groupby("Discount band", observed=True)["Profit"].agg(["mean", "sum", "count"]).round(1).reset_index()
    st.subheader("Discount vs profit")
    st.plotly_chart(px.bar(disc, x="Discount band", y="mean", labels={"mean": "Avg profit per order"},
                           color="mean", color_continuous_scale="RdYlGn"), use_container_width=True)

    # ---------- Auto insights ----------
    worst = cat.sort_values("Margin %").iloc[0]
    best_reg = reg.sort_values("Profit", ascending=False).iloc[0]
    loss = f[f["Profit"] < 0]
    high_disc_loss = loss[loss["Discount"] > 0.2]["Profit"].sum() / loss["Profit"].sum() * 100 if len(loss) else 0
    # NumPy: z-score outliers on profit
    z = (f["Profit"] - f["Profit"].mean()) / f["Profit"].std()
    outliers = int((np.abs(z) > 3).sum())
    st.subheader("Insights")
    st.info(f"**{worst['Category']}** has the lowest margin: {worst['Margin %']:.1f}%.")
    st.info(f"Orders with discount above 20% cause **{high_disc_loss:.0f}%** of total losses.")
    st.info(f"**{best_reg['Region']}** earns the most profit: ${best_reg['Profit']:,.0f}.")
    st.info(f"{outliers} orders have abnormal profit (z-score above 3). Check them for pricing errors.")
    st.subheader("Recommendations")
    st.markdown(f"- Cap discounts at 20% on **{worst['Category']}**.\n- Review pricing on loss-making products (see SQL tab).\n"
                f"- Push marketing in **{best_reg['Region']}** and grow weaker regions slowly.")

    # ---------- Excel export ----------
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"KPI": ["Total sales", "Total profit", "Margin %", "Orders"],
                      "Value": [round(sales, 2), round(profit, 2), round(profit / sales * 100, 2), f["Order ID"].nunique()]}).to_excel(w, sheet_name="Summary", index=False)
        cat.to_excel(w, sheet_name="By category", index=False)
        reg.to_excel(w, sheet_name="By region", index=False)
        monthly.to_excel(w, sheet_name="Monthly", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 18
    st.download_button("Download Excel report", buf.getvalue(), "sales_report.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- SQL ----------
with tab2:
    st.write("Same filtered data is loaded into a SQLite table named `orders`. Queries run live.")
    con = sqlite3.connect(":memory:")
    f.drop(columns=["Discount band"]).assign(**{"Order Date": f["Order Date"].dt.strftime("%Y-%m-%d")}) \
        .rename(columns=lambda c: c.replace(" ", "_").replace("-", "_").replace("%", "pct")).to_sql("orders", con, index=False)
    queries = {
        "Sales and profit by region": """SELECT Region, ROUND(SUM(Sales),0) AS sales, ROUND(SUM(Profit),0) AS profit,
       ROUND(SUM(Profit)*100.0/SUM(Sales),1) AS margin_pct
FROM orders GROUP BY Region ORDER BY profit DESC;""",
        "Top 10 loss-making products": """SELECT Product_Name, ROUND(SUM(Profit),0) AS total_profit, COUNT(*) AS orders
FROM orders GROUP BY Product_Name HAVING SUM(Profit) < 0
ORDER BY total_profit ASC LIMIT 10;""",
        "Best product per category (window function)": """SELECT * FROM (
  SELECT Category, Product_Name, ROUND(SUM(Profit),0) AS profit,
         RANK() OVER (PARTITION BY Category ORDER BY SUM(Profit) DESC) AS rnk
  FROM orders GROUP BY Category, Product_Name) WHERE rnk = 1;""",
        "Running total of monthly sales": """SELECT strftime('%Y-%m', Order_Date) AS month, ROUND(SUM(Sales),0) AS sales,
       ROUND(SUM(SUM(Sales)) OVER (ORDER BY strftime('%Y-%m', Order_Date)),0) AS running_total
FROM orders GROUP BY month ORDER BY month;""",
    }
    for title, q in queries.items():
        st.subheader(title)
        st.code(q, language="sql")
        st.dataframe(pd.read_sql(q, con), use_container_width=True)

# ---------- Cleaning report ----------
with tab3:
    st.write("What the app fixed automatically when loading your data:")
    st.dataframe(pd.DataFrame({"Check": ["Raw rows", "Duplicate rows removed", "Invalid dates", "Null discount (set to 0)",
                                         "Null profit (rows dropped)", "Clean rows"],
                               "Count": [report["rows_raw"], report["duplicates"], report["bad_dates"], report["null_discount"],
                                         report["null_profit"], report["rows_clean"]]}), hide_index=True)
