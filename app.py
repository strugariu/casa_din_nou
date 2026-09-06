import os
import streamlit as st
from playwright.sync_api import sync_playwright
import pandas as pd
import urllib.parse
from datetime import date, timedelta
import re
import base64
import plotly.express as px


# ==========================================
# 0. SETUP PLAYWRIGHT PENTRU CLOUD
# ==========================================
@st.cache_resource
def install_playwright():
    os.system("playwright install chromium")


install_playwright()


# ==========================================
# UTILAJE
# ==========================================
def extrage_numar(text):
    if not text or text == "N/A": return float('inf')
    text_fara_puncte = str(text).replace('.', '')
    numere = re.findall(r'\d+', text_fara_puncte)
    return int(numere[0]) if numere else float('inf')


def curata_rating(rating_string):
    if not rating_string: return "N/A"
    try:
        # Extragem primul număr din string (ex: "4,9 (120 evaluări)" -> 4.9)
        val = rating_string.split()[0].replace(',', '.')
        return val
    except:
        return "N/A"


def extrage_link_sigur_airbnb(item):
    base_url = "https://www.airbnb.com.ro/rooms"
    listing_id = item.get('listingId') or item.get('listing', {}).get('id')
    if listing_id: return f"{base_url}/{listing_id}"
    try:
        encoded_id = item.get('demandStayListing', {}).get('id', '')
        if encoded_id:
            decoded_bytes = base64.b64decode(encoded_id)
            return f"{base_url}/{decoded_bytes.decode('utf-8').split(':')[-1]}"
    except:
        pass
    return "https://www.airbnb.com.ro"


# ==========================================
# 1. SCRAPER BOOKING.COM (DOM PARSE + STEALTH)
# ==========================================
def scrape_booking(location, checkin, checkout, adults, rooms, max_pages, st_status, st_progress, progress_state):
    location_encoded = urllib.parse.quote(location)
    all_cabins = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = context.new_page()

        # Stealth Mode Nativ
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for page_num in range(max_pages):
            st_status.info(f"🌐 [Booking.com] Încărcăm pagina {page_num + 1}...")
            offset = page_num * 25
            url = f"https://www.booking.com/searchresults.ro.html?ss={location_encoded}&checkin={checkin}&checkout={checkout}&group_adults={adults}&no_rooms={rooms}&offset={offset}&selected_currency=RON"

            try:
                page.goto(url, timeout=60000)
                page.wait_for_timeout(3000)

                if page_num == 0:
                    try:
                        page.click('button#onetrust-accept-btn-handler', timeout=3000)
                    except:
                        pass

                page.wait_for_selector('[data-testid="property-card"]', timeout=10000)
            except Exception as e:
                titlu = page.title()
                st.error(f"Eroare Booking: Nu am găsit oferte. Probabil blocaj IP Cloud. (Titlu pagină: '{titlu}')")
                break

            cards = page.query_selector_all('[data-testid="property-card"]')
            if not cards: break

            for card in cards:
                title_el = card.query_selector('[data-testid="title"]')
                title = title_el.inner_text() if title_el else "N/A"

                dist_el = card.query_selector('[data-testid="distance"]')
                distance = dist_el.inner_text() if dist_el else "N/A"

                price_el = card.query_selector('[data-testid="price-and-discounted-price"]')
                price_text = price_el.inner_text().replace('\xa0', ' ') if price_el else "N/A"

                price_per_person = "N/A"
                if price_text != "N/A":
                    price_base = price_text.split(',')[0]
                    numeric_str = re.sub(r'[^\d]', '', price_base)
                    if numeric_str:
                        price_per_person = f"{int(numeric_str) // adults} lei"

                room_el = card.query_selector('[data-testid="recommended-units"]')
                room_info = "N/A"
                if room_el:
                    raw_info = room_el.inner_text()
                    raw_info = re.sub(r'Recomandare pentru grupul dumneavoastră[\r\n]*', '', raw_info,
                                      flags=re.IGNORECASE)
                    room_info = ' • '.join([line.strip() for line in raw_info.split('\n') if line.strip()])

                score_el = card.query_selector('[data-testid="review-score"] div:first-child')
                score = score_el.inner_text().replace('Scor:', '').strip() if score_el else "N/A"

                link_el = card.query_selector('a[data-testid="title-link"]')
                link = link_el.get_attribute('href') if link_el else "N/A"
                if link != "N/A" and link.startswith("/"): link = f"https://www.booking.com{link}"

                all_cabins.append({
                    "Platformă": "Booking.com",
                    "Nume Cabană": title,
                    "Distanță Centru": distance,
                    "Preț Total": price_text,
                    "Preț / Persoană": price_per_person,
                    "Configurație Camere": room_info,
                    "Scor": score,
                    "Link": link
                })

                progress_state['current'] += 1
                st_progress.progress(min(progress_state['current'] / progress_state['total'], 1.0))

        browser.close()
        return all_cabins


# ==========================================
# 2. SCRAPER AIRBNB (NETWORK INTERCEPT)
# ==========================================
def scrape_airbnb(location, checkin, checkout, adults, rooms, max_pages, st_status, st_progress, progress_state):
    location_encoded = urllib.parse.quote(location)
    all_cabins = []
    date_gasite_json = []

    def handle_response(response):
        if ("StaysSearch" in response.url or "ExploreSearch" in response.url) and response.request.method != "OPTIONS":
            try:
                json_data = response.json()
                if 'data' in json_data:
                    date_gasite_json.append(json_data)
            except:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.on("response", handle_response)

        # Iterăm prin pagini manual, modificând offset-ul
        for page_num in range(max_pages):
            st_status.info(f"🌐 [Airbnb] Încărcăm pagina {page_num + 1}...")
            offset = page_num * 18
            url = f"https://www.airbnb.com.ro/s/homes?query={location_encoded}&adults={adults}&min_bedrooms={rooms}&checkin={checkin}&checkout={checkout}&items_offset={offset}"

            page.goto(url)
            page.wait_for_timeout(5000)
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)

            progress_state['current'] += 18
            st_progress.progress(min(progress_state['current'] / progress_state['total'], 1.0))

        browser.close()

    # Procesăm JSON-urile capturate
    if not date_gasite_json:
        return []

    # Iterăm prin toate răspunsurile JSON capturate
    for rezultate_json in date_gasite_json:
        try:
            rezultate = rezultate_json['data']['presentation']['staysSearch']['results']['searchResults']
            for item in rezultate:
                if item.get('__typename') != 'StaySearchResult': continue

                titlu = item.get('title', '')
                subtitlu = item.get('subtitle', '')
                nume_complet = f"{titlu} - {subtitlu}"

                pret_total_num = extrage_numar(
                    item.get('structuredDisplayPrice', {}).get('primaryLine', {}).get('price', ''))
                if pret_total_num == float('inf'): continue

                pret_total_text = f"{pret_total_num} lei"
                pret_pers_text = f"{pret_total_num // adults} lei"
                rating = curata_rating(item.get('avgRatingLocalized', ''))
                link = extrage_link_sigur_airbnb(item)

                all_cabins.append({
                    "Platformă": "Airbnb",
                    "Nume Cabană": nume_complet,
                    "Distanță Centru": "Vezi pe hartă (Airbnb)",
                    "Preț Total": pret_total_text,
                    "Preț / Persoană": pret_pers_text,
                    "Configurație Camere": f"Min. {rooms} camere",
                    "Scor": rating,
                    "Link": link
                })
        except KeyError:
            continue

    return all_cabins


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
    buget_maxim = st.number_input("Buget max. per persoană (Lei)", min_value=10, max_value=5000, value=600, step=50)

if btn_extrage:
    if checkin >= checkout:
        st.error("Data de check-out trebuie să fie după data de check-in!")
    else:
        total_expected = 0
        if platforma in ["Booking.com", "Ambele"]: total_expected += max_pages * 25
        if platforma in ["Airbnb", "Ambele"]: total_expected += max_pages * 18

        progress_state = {'current': 0, 'total': total_expected if total_expected > 0 else 1}
        st_status = st.empty()
        st_progress = st.progress(0.0)

        # Nu mai avem nevoie de asyncio.run(), folosim execuție sincronă!
        date_extrase = []
        try:
            if platforma in ["Booking.com", "Ambele"]:
                rez_booking = scrape_booking(location, checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d"),
                                             adults, rooms, max_pages, st_status, st_progress, progress_state)
                date_extrase.extend(rez_booking)

            if platforma in ["Airbnb", "Ambele"]:
                rez_airbnb = scrape_airbnb(location, checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d"),
                                           adults, rooms, max_pages, st_status, st_progress, progress_state)
                date_extrase.extend(rez_airbnb)

            if date_extrase:
                df = pd.DataFrame(date_extrase)
                df = df.drop_duplicates(subset=['Nume Cabană', 'Link', 'Platformă'])
                df['Preț Numeric'] = df['Preț / Persoană'].apply(extrage_numar)

                st.session_state['date_cabane'] = df
                st_progress.progress(1.0)
                st_status.success("✅ Extragerea s-a finalizat cu succes!")
            else:
                st_status.warning("Nu am găsit rezultate valide. Posibil blocaj de securitate (Cloudflare).")
                st.session_state['date_cabane'] = None

        except Exception as e:
            st_status.error(f"Eroare severă la execuție: {e}")

if st.session_state['date_cabane'] is not None:
    df_memorie = st.session_state['date_cabane']

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

        st.subheader("📊 Analiză Vizuală (Grafice)")
        df_plots = df_filtered[df_filtered['Preț Numeric'] != float('inf')]

        if not df_plots.empty:
            col_chart1, col_chart2 = st.columns(2)
            color_map = {"Booking.com": "#003580", "Airbnb": "#FF5A5F"}

            with col_chart1:
                avg_price = df_plots.groupby('Platformă')['Preț Numeric'].mean().reset_index()
                fig_bar = px.bar(avg_price, x='Platformă', y='Preț Numeric', color='Platformă',
                                 title="Prețul Mediu estimat / Persoană (Lei)", text_auto='.0f',
                                 color_discrete_map=color_map)
                fig_bar.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Lei")
                fig_bar.update_traces(width=0.4)
                st.plotly_chart(fig_bar, use_container_width=True)

            with col_chart2:
                fig_hist = px.histogram(df_plots, x='Preț Numeric', color='Platformă',
                                        title="Distribuția Prețurilor / Persoană", nbins=15, barmode='group',
                                        text_auto=True, color_discrete_map=color_map)
                fig_hist.update_layout(xaxis_title="Preț / Persoană (Lei)", yaxis_title="Număr Proprietăți")
                fig_hist.update_traces(textposition='outside')
                st.plotly_chart(fig_hist, use_container_width=True)

        st.subheader("📋 Tabel Oferte")
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