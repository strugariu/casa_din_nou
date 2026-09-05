import streamlit as st
import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import urllib.parse
from datetime import date, timedelta
import re
import plotly.express as px

import os

@st.cache_resource
def install_playwright():
    os.system("playwright install chromium")

install_playwright()


# ==========================================
# 1. SCRAPER BOOKING.COM
# ==========================================
async def scrape_booking(location, checkin, checkout, adults, rooms, max_pages, st_status, st_progress, progress_state):
    location_encoded = urllib.parse.quote(location)
    all_cabins = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        for page_num in range(max_pages):
            st_status.info(f"🌐 [Booking.com] Încărcăm pagina {page_num + 1} de rezultate...")
            offset = page_num * 25
            url = f"https://www.booking.com/searchresults.ro.html?ss={location_encoded}&checkin={checkin}&checkout={checkout}&group_adults={adults}&no_rooms={rooms}&offset={offset}&selected_currency=RON"

            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(3000)

            if page_num == 0:
                try:
                    await page.click('button#onetrust-accept-btn-handler', timeout=3000)
                except:
                    pass

            try:
                await page.wait_for_selector('[data-testid="property-card"]', timeout=10000)
            except:
                break

            cards = await page.query_selector_all('[data-testid="property-card"]')
            if not cards:
                break

            for i, card in enumerate(cards):
                title_el = await card.query_selector('[data-testid="title"]')
                title = await title_el.inner_text() if title_el else "N/A"

                dist_el = await card.query_selector('[data-testid="distance"]')
                distance = await dist_el.inner_text() if dist_el else "N/A"

                price_el = await card.query_selector('[data-testid="price-and-discounted-price"]')
                price_text = await price_el.inner_text() if price_el else "N/A"

                price_per_person = "N/A"
                if price_text != "N/A":
                    price_base = price_text.split(',')[0]
                    numeric_str = re.sub(r'[^\d]', '', price_base)
                    if numeric_str:
                        total_price_num = int(numeric_str)
                        price_per_person = f"{total_price_num // adults} lei"

                room_el = await card.query_selector('[data-testid="recommended-units"]')
                if room_el:
                    room_info = await room_el.inner_text()
                    room_info = re.sub(r'Recomandare pentru grupul dumneavoastră[\r\n]*', '', room_info,
                                       flags=re.IGNORECASE)
                    room_info = ' • '.join([line.strip() for line in room_info.split('\n') if line.strip()])
                else:
                    room_info = "N/A"

                score_el = await card.query_selector('[data-testid="review-score"] div:first-child')
                if score_el:
                    score = await score_el.inner_text()
                    score = score.replace('Scor:', '').strip()
                else:
                    score = "N/A"

                link_el = await card.query_selector('a[data-testid="title-link"]')
                link = await link_el.get_attribute('href') if link_el else "N/A"
                if link != "N/A" and link.startswith("/"):
                    link = f"https://www.booking.com{link}"

                all_cabins.append({
                    "Platformă": "Booking.com",
                    "Nume Cabană": title,
                    "Distanță Centru": distance,
                    "Preț Total": price_text.replace('\xa0', ' '),
                    "Preț / Persoană": price_per_person,
                    "Configurație Camere": room_info,
                    "Scor": score,
                    "Link": link
                })

                # UPDATE PROGRESS
                progress_state['current'] += 1
                val = min(progress_state['current'] / progress_state['total'], 1.0)
                st_progress.progress(val)

        await browser.close()
        return all_cabins


# ==========================================
# 2. SCRAPER AIRBNB
# ==========================================
async def scrape_airbnb(location, checkin, checkout, adults, rooms, max_pages, st_status, st_progress, progress_state):
    location_encoded = urllib.parse.quote(location)
    all_cabins = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        for page_num in range(max_pages):
            st_status.info(f"🌐 [Airbnb] Încărcăm pagina {page_num + 1} de rezultate...")
            offset = page_num * 18
            url = f"https://www.airbnb.com/s/{location_encoded}/homes?checkin={checkin}&checkout={checkout}&adults={adults}&min_bedrooms={rooms}&items_offset={offset}&currency=RON"

            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(4000)

            try:
                await page.wait_for_selector('[data-testid="card-container"]', timeout=12000)
            except:
                break

            cards = await page.query_selector_all('[data-testid="card-container"]')
            if not cards:
                break

            for i, card in enumerate(cards):
                title_el = await card.query_selector('[data-testid="listing-card-title"]')
                title = await title_el.inner_text() if title_el else "N/A"

                subtitle_el = await card.query_selector('[data-testid="listing-card-subtitle"]')
                subtitle = await subtitle_el.inner_text() if subtitle_el else "N/A"
                distance = subtitle.replace('\n', ' • ')

                card_text = await card.inner_text()

                price_match = re.search(r'L\s*([\d,]+)\s*RON\s*total', card_text, re.IGNORECASE)
                price_text = "N/A"
                price_per_person = "N/A"

                if price_match:
                    numeric_str = price_match.group(1).replace(',', '')
                    total_price_num = int(numeric_str)
                    price_text = f"{total_price_num} lei"
                    price_per_person = f"{total_price_num // adults} lei"

                score_match = re.search(r'(\d[\.,]\d+)\s*\(\d+\)', card_text)
                score = score_match.group(1) if score_match else "N/A"

                link_el = await card.query_selector('a')
                link = await link_el.get_attribute('href') if link_el else "N/A"
                if link != "N/A" and link.startswith("/"):
                    link = f"https://www.airbnb.com{link.split('?')[0]}"

                all_cabins.append({
                    "Platformă": "Airbnb",
                    "Nume Cabană": title,
                    "Distanță Centru": distance,
                    "Preț Total": price_text,
                    "Preț / Persoană": price_per_person,
                    "Configurație Camere": f"Min. {rooms} camere",
                    "Scor": score,
                    "Link": link
                })

                # UPDATE PROGRESS
                progress_state['current'] += 1
                val = min(progress_state['current'] / progress_state['total'], 1.0)
                st_progress.progress(val)

        await browser.close()
        return all_cabins


# ==========================================
# 3. UTILAJE
# ==========================================
def extract_number(price_str):
    if price_str == "N/A":
        return float('inf')
    digits = re.sub(r'[^\d]', '', str(price_str))
    return int(digits) if digits else float('inf')


# ==========================================
# 4. INTERFAȚA STREAMLIT
# ==========================================
st.set_page_config(page_title="Scraper Cabane", page_icon="🏕️", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1 { color: #2ecc71; }
    </style>
""", unsafe_allow_html=True)

st.title("🏕️ Extractor Cabane - Booking & Airbnb")

if 'date_cabane' not in st.session_state:
    st.session_state['date_cabane'] = None

with st.sidebar:
    st.header("📍 Parametri Extragere")
    platforma = st.selectbox("Platformă", ["Booking.com", "Airbnb", "Ambele"])
    location = st.text_input("Locație", value="Brasov")

    default_checkin = date.today() + timedelta(days=14)
    default_checkout = default_checkin + timedelta(days=2)

    checkin = st.date_input("Check-in", value=default_checkin)
    checkout = st.date_input("Check-out", value=default_checkout)

    col_a, col_b = st.columns(2)
    with col_a:
        adults = st.number_input("Număr adulți", min_value=1, max_value=30, value=6)
    with col_b:
        rooms = st.number_input("Număr camere", min_value=1, max_value=30, value=3)

    max_pages = st.slider("Număr maxim pagini / platformă", min_value=1, max_value=10, value=2)

    btn_extrage = st.button("🔄 Trage Datele Noi", type="primary", use_container_width=True)

    st.divider()

    st.header("🎛️ Filtrează Datele")
    st.info("Se aplică instant pe datele descărcate.")
    buget_maxim = st.number_input("Buget max. per persoană (Lei)", min_value=10, max_value=5000, value=600, step=50)

if btn_extrage:
    if checkin >= checkout:
        st.error("Data de check-out trebuie să fie după data de check-in!")
    else:
        total_expected = 0
        if platforma in ["Booking.com", "Ambele"]:
            total_expected += max_pages * 25
        if platforma in ["Airbnb", "Ambele"]:
            total_expected += max_pages * 18

        progress_state = {'current': 0, 'total': total_expected if total_expected > 0 else 1}

        st_status = st.empty()
        st_progress = st.progress(0.0)

        st_status.info("🚀 Pornim browser-ul și pregătim căutarea...")

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            date_extrase = []

            if platforma in ["Booking.com", "Ambele"]:
                rez_booking = loop.run_until_complete(
                    scrape_booking(location, checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d"), adults,
                                   rooms, max_pages, st_status, st_progress, progress_state)
                )
                date_extrase.extend(rez_booking)

            if platforma in ["Airbnb", "Ambele"]:
                rez_airbnb = loop.run_until_complete(
                    scrape_airbnb(location, checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d"), adults,
                                  rooms, max_pages, st_status, st_progress, progress_state)
                )
                date_extrase.extend(rez_airbnb)

            if date_extrase:
                df = pd.DataFrame(date_extrase)
                df = df.drop_duplicates(subset=['Nume Cabană', 'Link', 'Platformă'])

                # Creăm o coloană numerică pentru calcule și grafice
                df['Preț Numeric'] = df['Preț / Persoană'].apply(extract_number)

                st.session_state['date_cabane'] = df
                st_progress.progress(1.0)
                st_status.success("✅ Extragerea s-a finalizat cu succes!")
            else:
                st_status.warning("Nu am găsit rezultate.")
                st.session_state['date_cabane'] = None

        except Exception as e:
            st_status.error(f"Eroare în timpul executării: {e}")
            st.session_state['date_cabane'] = None

if st.session_state['date_cabane'] is not None:
    df_memorie = st.session_state['date_cabane']

    # Filtrăm pe baza bugetului maxim
    mask = df_memorie['Preț Numeric'] <= buget_maxim
    df_filtered = df_memorie[mask].reset_index(drop=True)

    st.divider()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏨 Oferte Extrase", len(df_memorie))
    col2.metric("✅ Oferte în Buget", len(df_filtered))

    if not df_filtered.empty:
        min_price = df_filtered['Preț Numeric'].min()
        col3.metric("💰 Cel mai mic preț/pers", f"{int(min_price)} lei")

        booking_count = len(df_filtered[df_filtered['Platformă'] == 'Booking.com'])
        airbnb_count = len(df_filtered[df_filtered['Platformă'] == 'Airbnb'])
        col4.metric("📊 Surse (Bkg / Airbnb)", f"{booking_count} / {airbnb_count}")

        # -----------------------------------------
        # GRAFICE (Analiză Vizuală)
        # -----------------------------------------
        st.subheader("📊 Analiză Vizuală (Grafice)")

        # Eliminăm rândurile cu preț 'inf' (cele care nu au preț disponibil) pentru grafice corecte
        df_plots = df_filtered[df_filtered['Preț Numeric'] != float('inf')]

        if not df_plots.empty:
            col_chart1, col_chart2 = st.columns(2)

            # Culorile brandurilor
            color_map = {"Booking.com": "#003580", "Airbnb": "#FF5A5F"}

            with col_chart1:
                # Grafic: Preț Mediu
                avg_price = df_plots.groupby('Platformă')['Preț Numeric'].mean().reset_index()
                fig_bar = px.bar(
                    avg_price,
                    x='Platformă',
                    y='Preț Numeric',
                    color='Platformă',
                    title="Prețul Mediu estimat / Persoană (Lei)",
                    text_auto='.0f',
                    color_discrete_map=color_map
                )
                fig_bar.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Lei")

                # FORȚĂM LĂȚIMEA BAREI: astfel nu va mai acoperi tot ecranul dacă există doar o platformă
                fig_bar.update_traces(width=0.4)

                st.plotly_chart(fig_bar, use_container_width=True)

            with col_chart2:
                # Grafic: Distribuția Prețurilor (Histogramă)
                fig_hist = px.histogram(
                    df_plots,
                    x='Preț Numeric',
                    color='Platformă',
                    title="Distribuția Prețurilor / Persoană",
                    nbins=15,
                    barmode='group',  # Arată platformele una lângă alta, nu suprapuse
                    text_auto=True,  # ADĂUGĂM NUMĂRUL DIRECT PE BARE
                    color_discrete_map=color_map
                )
                fig_hist.update_layout(xaxis_title="Preț / Persoană (Lei)", yaxis_title="Număr Proprietăți")

                # Formatăm textul de pe bare să arate curat
                fig_hist.update_traces(textposition='outside')

                st.plotly_chart(fig_hist, use_container_width=True)

        # -----------------------------------------
        # TABELUL CU OFERTE
        # -----------------------------------------
        st.subheader("📋 Tabel Oferte")

        # Ascundem coloana calculată numeric din tabel pentru aspect curat
        df_display = df_filtered.drop(columns=['Preț Numeric'], errors='ignore')

        st.dataframe(
            df_display,
            column_config={
                "Platformă": st.column_config.TextColumn("Platformă", width="small"),
                "Link": st.column_config.LinkColumn("Deschide Oferta"),
                "Distanță Centru": st.column_config.TextColumn("Distanță / Zonă", width="small")
            },
            hide_index=True,
            use_container_width=True
        )

        csv = df_display.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descarcă tabelul (CSV)", data=csv, file_name=f'cabane_{location}.csv', mime='text/csv')
    else:
        st.warning(f"Niciuna din ofertele extrase nu se încadrează sub {buget_maxim} lei / persoană.")
