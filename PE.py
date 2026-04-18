import streamlit as st
import requests
import pandas as pd

# 1. 网页基础设置
st.set_page_config(page_title="A股2026一季报监控", layout="wide")
st.title("📈 2026年一季报业绩监控：预告 vs 正式")

# 侧边栏增加手动刷新
if st.sidebar.button("🔄 同步盘中实时价 (清除缓存)"):
    st.cache_data.clear()

@st.cache_data(ttl=30) # 盘中建议设置 30 秒刷新一次
def fetch_data(report_mode="forecast"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://quote.eastmoney.com/"
    }
    
    df_f = pd.DataFrame()
    report_name = "RPT_PUBLIC_OP_NEWPREDICT" if report_mode == "forecast" else "RPT_LICO_FN_CPD"
    
    # 日期字段自适应
    for date_key in ["REPORTDATE", "REPORT_DATE"]:
        filter_str = f"({date_key}='2026-03-31')"
        url = f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName={report_name}&columns=ALL&filter={filter_str}&pageNumber=1&pageSize=6000"
        if report_mode != "forecast":
            url += "&sortColumns=SECURITY_CODE&sortTypes=1"
        
        try:
            r = requests.get(url, headers=headers, timeout=10).json()
            if r and r.get('result') and r['result'].get('data'):
                df_f = pd.DataFrame(r['result']['data'])
                if not df_f.empty: break
        except: continue
            
    if df_f.empty: return pd.DataFrame()

    if report_mode == "forecast":
        if 'PREDICT_FINANCE_CODE' in df_f.columns:
            df_f = df_f[df_f['PREDICT_FINANCE_CODE'].isin(['004', '005'])]
    
    df_f = df_f.sort_values(by=['SECURITY_CODE']).drop_duplicates(subset=['SECURITY_CODE'])

    # === B. 行情抓取 (盘中实时核心) ===
    codes = df_f['SECURITY_CODE'].astype(str).str.zfill(6).tolist()
    secids = [f"1.{c}" if c.startswith('6') else f"0.{c}" for c in codes]

    all_m = []
    for i in range(0, len(secids), 200):
        batch = ",".join(secids[i:i+200])
        url_m = f"http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={batch}&fields=f2,f12,f14,f20,f100"
        try:
            rm = requests.get(url_m, headers=headers, timeout=5).json()
            diff = rm.get('data', {}).get('diff', [])
            if isinstance(diff, dict): diff = list(diff.values())
            all_m.extend(diff)
        except: continue

    df_m = pd.DataFrame(all_m)
    if df_m.empty: return pd.DataFrame()
    
    df_m['f12'] = df_m['f12'].astype(str).str.zfill(6)
    df_m = df_m.drop_duplicates(subset=['f12']).rename(columns={'f2': '最新价', 'f12': '股票代码', 'f20': '总市值', 'f100': '所属行业'})
    
    # === C. 合并与清洗 ===
    df = pd.merge(df_f, df_m, left_on='SECURITY_CODE', right_on='股票代码', how='left')
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
    df = df[df['最新价'] > 0].dropna(subset=['最新价']) 
    df['总市值(亿)'] = (pd.to_numeric(df['总市值'], errors='coerce') / 1e8).round(2)
    df['所属行业'] = df['所属行业'].fillna('其他').replace('', '其他')

    content_col = 'PREDICT_CONTENT' if 'PREDICT_CONTENT' in df.columns else None

    if report_mode == "forecast":
        df['下限(亿)'] = (pd.to_numeric(df['PREDICT_AMT_LOWER'], errors='coerce') / 1e8).round(2)
        df['上限(亿)'] = (pd.to_numeric(df['PREDICT_AMT_UPPER'], errors='coerce') / 1e8).round(2)
        df['中值(亿)'] = ((df['下限(亿)'] + df['上限(亿)']) / 2).round(2)
        df['增速下限(%)'] = pd.to_numeric(df['ADD_AMP_LOWER'], errors='coerce').round(2)
        df['增速上限(%)'] = pd.to_numeric(df['ADD_AMP_UPPER'], errors='coerce').round(2)
        df['增速中值(%)'] = ((df['增速下限(%)'] + df['增速上限(%)']) / 2).round(2)
        df['PE(下)'] = (df['总市值(亿)'] / (df['下限(亿)'] * 4)).round(2)
        df['PE(上)'] = (df['总市值(亿)'] / (df['上限(亿)'] * 4)).round(2)
        df['业绩说明'] = df[content_col].fillna("暂无说明") if content_col else "暂无说明"
        
        cols = ['股票代码', 'SECURITY_NAME_ABBR', '所属行业', '最新价', '总市值(亿)', 'PREDICT_TYPE', 
                '下限(亿)', '上限(亿)', '中值(亿)', '增速下限(%)', '增速上限(%)', '增速中值(%)', 
                'PE(下)', 'PE(上)', '业绩说明']
        return df[cols].rename(columns={'SECURITY_NAME_ABBR': '股票简称', 'PREDICT_TYPE': '类型'})
    else:
        profit_col = 'PARENT_NETPROFIT' if 'PARENT_NETPROFIT' in df.columns else 'NETPROFIT'
        df['净利润(亿)'] = (pd.to_numeric(df[profit_col], errors='coerce') / 1e8).round(2)
        yoy_col = 'SJLTZ' if 'SJLTZ' in df.columns else 'QN_YOYNETPROFIT'
        df['同比增长(%)'] = pd.to_numeric(df[yoy_col], errors='coerce').round(2)
        df['动态PE'] = (df['总市值(亿)'] / (df['净利润(亿)'] * 4)).round(2)
        df['业绩说明'] = df[content_col].fillna("正式报表披露") if content_col else "正式报表披露"
        
        cols = ['股票代码', 'SECURITY_NAME_ABBR', '所属行业', '最新价', '总市值(亿)', '净利润(亿)', '同比增长(%)', '动态PE', '业绩说明']
        return df[cols].rename(columns={'SECURITY_NAME_ABBR': '股票简称'})

# --- 3. 页面渲染 ---
st.sidebar.header("🎯 核心筛选")
df_raw_f = fetch_data("forecast")
df_raw_a = fetch_data("actual")

industry_set = set()
if not df_raw_f.empty: industry_set.update(df_raw_f['所属行业'].unique().tolist())
if not df_raw_a.empty: industry_set.update(df_raw_a['所属行业'].unique().tolist())

selected_ind = st.sidebar.multiselect("📁 选择一级行业", sorted(list(industry_set)))
search = st.sidebar.text_input("🔍 搜索代码/简称", "")

# 重点：配置列样式
column_config = {
    "业绩说明": st.column_config.TextColumn(
        "业绩说明原文",
        help="点击或悬停查看完整公告内容",
        width="large",  # 限制初始宽度
    ),
    "股票代码": st.column_config.TextColumn("代码", width="small"),
    "最新价": st.column_config.NumberColumn("最新价", format="%.2f"),
    "动态PE": st.column_config.NumberColumn("PE", format="%.2f"),
}

tab1, tab2 = st.tabs(["📢 业绩预告 (全指标)", "📑 正式一季报 (定稿数据)"])

with tab1:
    if not df_raw_f.empty:
        df1 = df_raw_f.copy()
        if selected_ind: df1 = df1[df1['所属行业'].isin(selected_ind)]
        if search: df1 = df1[df1['股票代码'].str.contains(search) | df1['股票简称'].str.contains(search)]
        st.success(f"📊 符合条件：{len(df1)} 家")
        # 使用 st.data_editor 或 st.dataframe 配合 column_config
        st.dataframe(df1, hide_index=True, height=750, column_config=column_config, use_container_width=True)

with tab2:
    if not df_raw_a.empty:
        df2 = df_raw_a.copy()
        if selected_ind: df2 = df2[df2['所属行业'].isin(selected_ind)]
        if search: df2 = df2[df2['股票代码'].str.contains(search) | df2['股票简称'].str.contains(search)]
        st.success(f"🔥 符合条件：{len(df2)} 家")
        st.dataframe(df2, hide_index=True, height=750, column_config=column_config, use_container_width=True)
