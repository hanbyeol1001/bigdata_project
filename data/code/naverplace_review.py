from __future__ import annotations
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException
)
from selenium.webdriver import ActionChains

from bs4 import BeautifulSoup
from openpyxl import Workbook

import csv
import re
import time
import datetime
import random
import os
import traceback


# ==============================
# 디버그 설정 및 저장 유틸
# ==============================
DEBUG = True

def _ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def save_html(driver, name: str):
    if not DEBUG: return
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    path = os.path.join(os.getcwd(), f"{name}_{_ts()}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[DEBUG] HTML 저장: {path}")
    except Exception as e:
        print(f"[DEBUG] HTML 저장 실패({name}): {e}")

def save_iframe_html(driver, name: str, iframe_css="#searchIframe, iframe[id*='search'], iframe[name*='search']"):
    if not DEBUG: return
    try:
        driver.switch_to.default_content()
        iframe = driver.find_element(By.CSS_SELECTOR, iframe_css)
        driver.switch_to.frame(iframe)
        path = os.path.join(os.getcwd(), f"{name}_{_ts()}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.switch_to.default_content()
        print(f"[DEBUG] IFRAME HTML 저장: {path}")
    except Exception as e:
        print(f"[DEBUG] IFRAME 저장 실패({name}): {e}")


# ==============================
# 콘솔 색상 (로깅용)
# ==============================
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'


# ==============================
# 공용 유틸 (대기/오버레이/안전클릭)
# ==============================
def wait_presence(driver, locator, timeout=10):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))

def wait_visible(driver, locator, timeout=10):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))

def wait_clickable(driver, locator, timeout=10):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))

def close_common_overlays(driver):
    """쿠키 배너/앱 유도/모달 등 흔한 오버레이 닫기 시도."""
    candidates = [
        (By.XPATH, "//button[contains(@aria-label,'닫기') or contains(@aria-label,'close')]"),
        (By.XPATH, "//a[contains(@aria-label,'닫기') or contains(@aria-label,'close')]"),
        (By.XPATH, "//*[self::a or self::button][contains(.,'닫기') or contains(.,'거부') or contains(.,'확인')]"),
        (By.XPATH, "//*[@role='button' and (contains(.,'닫기') or contains(@aria-label,'닫기'))]"),
    ]
    for loc in candidates:
        try:
            el = WebDriverWait(driver, 0.8).until(EC.element_to_be_clickable(loc))
            driver.execute_script("arguments[0].click();", el)
            time.sleep(0.15)
        except Exception:
            pass

def center_and_mouseover(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    try:
        ActionChains(driver).move_to_element(element).perform()
    except Exception:
        pass

def is_covered_by_other_element(driver, element):
    """요소 중앙에서 elementFromPoint로 다른 엘리먼트가 덮고 있는지 확인."""
    try:
        rect = driver.execute_script("""
            const r = arguments[0].getBoundingClientRect();
            return {x: r.left + r.width/2, y: r.top + r.height/2};
        """, element)
        covering = driver.execute_script("""
            return document.elementFromPoint(arguments[0].x, arguments[0].y);
        """, rect)
        return covering and covering is not element and not element.contains(covering)
    except Exception:
        return False

def safe_click(driver, locator, timeout=10, retries=4, refind_each_try=True, use_js_fallback=True, label:str=""):
    """
    안전 클릭:
    1) presence → visible → clickable
    2) 중앙 스크롤 + 마우스오버
    3) 덮임 감지 시 오버레이 닫고 재시도
    4) 일반 클릭 실패 시 JS 클릭 폴백
    5) stale/intercept/timeout 재시도
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            if refind_each_try or attempt == 1:
                wait_presence(driver, locator, timeout)
                el = wait_visible(driver, locator, timeout)

            center_and_mouseover(driver, el)

            if is_covered_by_other_element(driver, el):
                close_common_overlays(driver)
                time.sleep(0.15)

            el = wait_clickable(driver, locator, timeout)
            center_and_mouseover(driver, el)

            try:
                el.click()
            except ElementClickInterceptedException:
                if use_js_fallback:
                    driver.execute_script("arguments[0].click();", el)
                else:
                    raise

            time.sleep(random.uniform(0.25, 0.5))
            return True

        except (StaleElementReferenceException, ElementClickInterceptedException,
                TimeoutException, NoSuchElementException) as e:
            last_err = e
            print(f"{Colors.YELLOW}[safe_click] 재시도 {attempt}/{retries} - locator={locator} label={label} err={type(e).__name__}{Colors.RESET}")
            close_common_overlays(driver)
            try:
                driver.execute_script("window.scrollBy(0, 140);")
            except Exception:
                pass
            time.sleep(0.2 + 0.2 * attempt)
            continue
        except Exception as e:
            last_err = e
            print(f"{Colors.YELLOW}[safe_click] 예외 - locator={locator} label={label} err={e}{Colors.RESET}")
            break

    if last_err:
        print(f"{Colors.YELLOW}[safe_click] 최종 실패 - locator={locator} label={label} err={last_err}{Colors.RESET}")
        save_html(driver, f"debug_safe_click_fail_outer_{label or 'unknown'}")
        # 가능한 경우: 현재 프레임도 저장
        try:
            save_iframe_html(driver, f"debug_safe_click_fail_iframe_{label or 'unknown'}")
        except Exception:
            pass
    return False


# ==============================
# 크롤러 클래스
# ==============================
class NaverMapReviewCrawler:
    def __init__(self, headless: bool = False, max_clicks: int = 30, wait_sec: int = 15):
        self.options = webdriver.ChromeOptions()
        if headless:
            self.options.add_argument('--headless=new')
        self.options.add_argument('window-size=1920,1080')
        self.options.add_argument('--disable-blink-features=AutomationControlled')
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.options.add_experimental_option('useAutomationExtension', False)
        self.options.add_argument(
            'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # Selenium Manager 사용 (webdriver_manager 불필요)
        self.driver = webdriver.Chrome(options=self.options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, wait_sec)

        # 대상 식당
        self.restaurants = ["성화해장국 인하점"]

        self.max_clicks = max_clicks
        self.review_rows = []  # [restaurant_name, nickname, content, date, revisit]
        self.now = datetime.datetime.now()

    # ------------- 검색/프레임/결과 클릭 -------------
    def open_naver_map(self):
        self.driver.get("https://map.naver.com/")
        self.driver.implicitly_wait(1)
        time.sleep(2.0)

    def search_restaurant(self, keyword: str) -> bool:
        try:
            self.open_naver_map()
            selectors = [
                (By.CSS_SELECTOR, "input[placeholder*='검색']"),
                (By.CSS_SELECTOR, ".input_search"),
                (By.CSS_SELECTOR, "#search-input"),
                (By.CSS_SELECTOR, "input[class*='search']"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.CSS_SELECTOR, ".search_input"),
                (By.CSS_SELECTOR, "[placeholder*='장소']"),
            ]
            box = None
            for loc in selectors:
                try:
                    box = self.wait.until(EC.element_to_be_clickable(loc))
                    if box:
                        break
                except Exception:
                    continue
            if not box:
                print(f"{Colors.RED}검색창을 찾지 못했습니다.{Colors.RESET}")
                return False
            box.clear()
            query = f"인천 {keyword}"
            box.send_keys(query)
            box.send_keys(Keys.RETURN)
            time.sleep(1.5)
            print(f"{Colors.GREEN}검색 실행: {keyword}{Colors.RESET}")
            return True
        except Exception as e:
            print(f"{Colors.RED}검색 오류: {e}{Colors.RESET}")
            return False

    def _switch_to_search_iframe(self) -> bool:
        """검색결과 iframe(#searchIframe)로 전환. 없으면 프레임 없는 레이아웃으로 간주."""
        try:
            self.driver.switch_to.default_content()
            for _ in range(15):  # 최대 ~15초 폴링
                iframes = self.driver.find_elements(By.CSS_SELECTOR, "#searchIframe, iframe[id*='search'], iframe[name*='search']")
                if iframes:
                    try:
                        self.driver.switch_to.frame(iframes[0])
                        return True
                    except Exception:
                        pass
                time.sleep(1.0)
            return True  # 프레임이 아예 없는 레이아웃 가능성
        except Exception:
            return False

    def click_first_result(self) -> bool:
        """
        검색 결과에서 상세로 진입:
        1) '/place/' 혹은 유사 링크를 직접 찾아 클릭
        2) 실패 시 카드형 첫 항목을 안전 클릭
        """
        try:
            if not self._switch_to_search_iframe():
                print(f"{Colors.YELLOW}검색 iframe 전환 실패(프레임 없는 레이아웃일 수 있음){Colors.RESET}")

            # 1) 앵커 href로 진입 시도
            def find_links(drv):
                try:
                    return drv.find_elements(By.CSS_SELECTOR,
                                             'a[href*="/place/"], a[href*="/entry/place/"], a[href*="/p/entry/"]')
                except Exception:
                    return []

            links = None
            for _ in range(20):
                links = find_links(self.driver)
                if links:
                    break
                time.sleep(0.6)

            if links:
                first = links[0]
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", first)
                    time.sleep(0.2)
                except Exception:
                    pass
                try:
                    first.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", first)
                    except Exception as e:
                        print(f"{Colors.YELLOW}PC 검색결과 JS 클릭도 실패: {e}{Colors.RESET}")
                        links = None  # 아래 카드 클릭 폴백

            # 2) 카드형 첫 항목 클릭 폴백
            if not links:
                card_candidates = [
                    (By.CSS_SELECTOR, "li._1EKsQ._1O3jB"),
                    (By.CSS_SELECTOR, "div._3ZdcN"),
                    (By.CSS_SELECTOR, "._2kAri._1wTD9"),
                    (By.CSS_SELECTOR, ".search_item"),
                    (By.CSS_SELECTOR, ".place_item"),
                    (By.CSS_SELECTOR, ".item_place"),
                ]
                clicked = False
                for loc in card_candidates:
                    if safe_click(self.driver, loc, timeout=6, retries=3, label="first_result_card"):
                        clicked = True
                        break
                if not clicked:
                    print(f"{Colors.RED}검색 결과 클릭 실패{Colors.RESET}")
                    save_iframe_html(self.driver, "debug_no_place_link_iframe")
                    save_html(self.driver, "debug_no_place_link_outer")
                    return False

            time.sleep(1.5)
            print(f"{Colors.GREEN}첫 검색 결과 클릭 성공{Colors.RESET}")
            return True

        except Exception as e:
            print(f"{Colors.RED}첫 결과 클릭 예외: {e}{Colors.RESET}")
            traceback.print_exc()
            save_html(self.driver, "debug_click_first_result_exception")
            return False

    # ------------- entryIframe 전환 + 탭 클릭 -------------
    def switch_to_entry_iframe(self) -> bool:
        try:
            self.driver.switch_to.default_content()
            iframe = WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#entryIframe, iframe[id*='entry'], iframe[name*='entry']"))
            )
            self.driver.switch_to.frame(iframe)
            return True
        except Exception as e:
            print(f"{Colors.RED}entryIframe 전환 실패: {e}{Colors.RESET}")
            save_html(self.driver, "debug_entry_iframe_fail_outer")
            return False

    def _wait_tab_selected_or_reviews_visible(self, tab_text: str, timeout: int = 10) -> bool:
        """탭 클릭 후 활성화 또는 리뷰 영역 노출 대기."""
        # 1) aria-selected='true'
        try:
            WebDriverWait(self.driver, timeout//2).until(EC.presence_of_element_located(
                (By.XPATH, f"//a[@role='tab' and @aria-selected='true'][span[contains(normalize-space(.),'{tab_text}')]]")
            ))
            return True
        except Exception:
            pass
        # 2) 리뷰 섹션/리스트 존재
        review_presence_locators = [
            (By.CSS_SELECTOR, "[data-nclicks-area*='rvw']"),
            (By.XPATH, "//*[contains(normalize-space(.),'리뷰')]"),
            (By.CSS_SELECTOR, "ul li[role='listitem']"),
        ]
        for loc in review_presence_locators:
            try:
                WebDriverWait(self.driver, timeout//2).until(EC.presence_of_element_located(loc))
                return True
            except Exception:
                continue
        return False

    def click_tab(self, tab_text: str,
                  iframe_css: str = "#entryIframe, iframe[id*='entry'], iframe[name*='entry']") -> bool:
        """
        entryIframe 안에서 탭 라벨(예: '리뷰')을 찾아 클릭.
        우선 JS로 텍스트 매칭 탭을 찾아 클릭 → 실패 시 안전 클릭 다중 시도.
        """
        try:
            # 1) 상세 iframe 진입
            self.driver.switch_to.default_content()
            iframe = WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, iframe_css))
            )
            self.driver.switch_to.frame(iframe)

            close_common_overlays(self.driver)

            # 2) JS로 텍스트 매칭 탭 찾고 클릭 (가장 견고)
            js = r"""
            const text = arguments[0];
            const norm = s => s ? s.replace(/\s+/g,' ').trim() : '';
            // role=tab 후보 모두
            let cands = Array.from(document.querySelectorAll('a[role="tab"],button[role="tab"],[role="tab"]'));
            let el = cands.find(e => norm(e.textContent).includes(text));
            if (!el) {
              // span.veBoZ 혹은 일반 span에서 조상탭 탐색
              const spans = Array.from(document.querySelectorAll('span'));
              const sp = spans.find(s => norm(s.textContent) === text || norm(s.textContent).includes(text));
              if (sp) el = sp.closest('a[role="tab"],button[role="tab"],[role="tab"]') || sp.closest('div');
            }
            if (el) {
              el.scrollIntoView({block:'center'});
              el.click();
              return true;
            }
            return false;
            """
            clicked_js = False
            try:
                clicked_js = self.driver.execute_script(js, tab_text)
            except Exception:
                clicked_js = False

            if clicked_js:
                if self._wait_tab_selected_or_reviews_visible(tab_text, timeout=10):
                    print(f"{Colors.GREEN}{tab_text} 탭(JS) 클릭 성공{Colors.RESET}")
                    return True

            # 3) 안전 클릭 다중 시도
            locators = [
                (By.XPATH, f"//a[@role='tab'][span[normalize-space()='{tab_text}']]"),
                (By.XPATH, f"//a[@role='tab'][contains(normalize-space(.), '{tab_text}')]"),
                (By.XPATH, f"//button[@role='tab'][span[normalize-space()='{tab_text}']]"),
                (By.XPATH, f"//button[@role='tab'][contains(normalize-space(.), '{tab_text}')]"),
                (By.XPATH, f"//span[contains(@class,'veBoZ') and normalize-space()='{tab_text}']"),
                (By.XPATH, f"//span[normalize-space()='{tab_text}']"),
            ]
            for loc in locators:
                if safe_click(self.driver, loc, timeout=8, retries=3, label=f"tab_{tab_text}"):
                    if self._wait_tab_selected_or_reviews_visible(tab_text, timeout=10):
                        print(f"{Colors.GREEN}{tab_text} 탭 클릭 성공{Colors.RESET}")
                        return True

            print(f"{Colors.YELLOW}[click_tab] '{tab_text}' 탭을 찾거나 활성화하지 못했습니다.{Colors.RESET}")
            save_iframe_html(self.driver, f"debug_tab_fail_{tab_text}")
            return False

        except Exception as e:
            print(f"{Colors.RED}[click_tab] 예외: {e}{Colors.RESET}")
            traceback.print_exc()
            save_html(self.driver, f"debug_click_tab_exception_{tab_text}")
            return False

    def click_review_tab(self) -> bool:
        return self.click_tab("리뷰")

    # ------------- 리뷰 더보기(PC entry) -------------
    def expand_reviews_in_entry(self, max_clicks: int | None = None):
        """entryIframe 내부에서 리뷰 '더보기'를 가능한 많이 펼친다."""
        if not self.switch_to_entry_iframe():
            return

        if max_clicks is None:
            max_clicks = self.max_clicks

        more_locators = [
            (By.XPATH, "//*[self::a or self::button][contains(., '더보기')]"),
            (By.XPATH, "//*[self::a or self::button][contains(@aria-label, '더보기')]"),
            (By.XPATH, "//*[@role='button' and contains(., '더보기')]"),
        ]

        clicks = 0
        while clicks < max_clicks:
            close_common_overlays(self.driver)
            found_and_clicked = False
            for loc in more_locators:
                if safe_click(self.driver, loc, timeout=4, retries=2, label="reviews_more"):
                    clicks += 1
                    found_and_clicked = True
                    time.sleep(0.4)
                    break
            if not found_and_clicked:
                print(f"{Colors.YELLOW}더보기 버튼 없음/완료 (총 {clicks}회 클릭){Colors.RESET}")
                break

        if clicks >= max_clicks:
            print(f"{Colors.BLUE}더보기 최대 클릭({max_clicks}) 도달{Colors.RESET}")
        time.sleep(0.8)

    # ------------- 리뷰 파싱(PC entry) -------------
    def parse_reviews_in_entry(self, restaurant_name: str):
        """entryIframe의 현재 DOM에서 리뷰 파싱(구조 기반)."""
        if not self.switch_to_entry_iframe():
            return

        html = self.driver.page_source
        soup = BeautifulSoup(html, 'lxml')

        # 1) 리뷰 리스트 루트 후보
        review_root_candidates = [
            '#app-root [role="region"]',
            '#app-root [data-nclicks-area*="rvw"]',
            '#app-root',
        ]

        # 2) 아이템 후보: role=listitem 또는 li
        items = []
        for root_sel in review_root_candidates:
            root = soup.select_one(root_sel)
            if not root:
                continue
            items = root.select('li[role="listitem"]')
            if not items:
                items = root.select('li')
            if items:
                break

        extracted = 0
        for li in items:
            text_all = li.get_text(" ", strip=True)
            # 간단 필터: 리뷰 관련 단서
            if not any(k in text_all for k in ["리뷰", "방문", "년", "월", "일", "재방문", "좋아요", "별점", "202", "201"]):
                continue

            # 닉네임
            nickname = ""
            nn_candidates = [
                'a[aria-label*="님"]',
                'div[class*="profile"] span',
                'span'
            ]
            for sel in nn_candidates:
                el = li.select_one(sel)
                if el and el.get_text(strip=True):
                    nickname = el.get_text(strip=True)
                    break

            # 본문(리뷰 텍스트)
            content = ""
            content_candidates = [
                'div[aria-expanded] *',
                'div[class*="review"] *',
                'p', 'span'
            ]
            for sel in content_candidates:
                el = li.select_one(sel)
                if el and el.get_text(strip=True):
                    val = el.get_text(" ", strip=True)
                    if len(val) >= 5:
                        content = val
                        break

            # 날짜
            date_txt = ""
            for sel in ['time', 'span[class*="date"]', 'em', 'span']:
                el = li.select_one(sel)
                if el and re.search(r'(\d{4}\.\d{1,2}\.\d{1,2}|[0-9]{4}년|[0-9]{1,2}월|[0-9]{1,2}일)', el.get_text(strip=True)):
                    date_txt = el.get_text(strip=True)
                    break

            # 재방문 여부
            revisit = ""
            for sp in li.find_all('span'):
                t = sp.get_text(strip=True)
                if "재방문" in t or "재방문 의사" in t:
                    revisit = t
                    break

            if not content:
                continue

            self.review_rows.append([restaurant_name, nickname, content, date_txt, revisit])
            extracted += 1

        print(f"{Colors.GREEN}{restaurant_name}: {extracted}개 리뷰 파싱(PC entry) 완료{Colors.RESET}")

    # ------------- 저장 -------------
    def save_to_excel(self, filename: str | None = None):
        if not filename:
            filename = f'naver_review_{self.now.strftime("%Y-%m-%d_%H-%M-%S")}.xlsx'
        wb = Workbook()
        ws = wb.active
        ws.title = 'output'
        ws.append(['restaurant_name', 'nickname', 'content', 'date', 'revisit'])
        for row in self.review_rows:
            ws.append(row)
        wb.save(filename)
        print(f"{Colors.CYAN}엑셀 저장 완료: {filename} (총 {len(self.review_rows)}개){Colors.RESET}")

    def save_to_csv(self, filename: str = "naver_reviews.csv"):
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['restaurant_name', 'nickname', 'content', 'date', 'revisit'])
            w.writerows(self.review_rows)
        print(f"{Colors.CYAN}CSV 저장 완료: {filename} (총 {len(self.review_rows)}개){Colors.RESET}")

    # ------------- 파이프라인 -------------
    def crawl_one(self, restaurant_name: str):
        print(f"{Colors.MAGENTA}=== {restaurant_name} 수집 시작 ==={Colors.RESET}")
        if not self.search_restaurant(restaurant_name):
            print(f"{Colors.YELLOW}검색 실패 → 건너뜀{Colors.RESET}")
            return

        if not self.click_first_result():
            print(f"{Colors.YELLOW}검색결과 클릭 실패 → 건너뜀{Colors.RESET}")
            return

        # 리뷰 탭 클릭 (span.veBoZ='리뷰' 포함 로직 + JS 우선)
        if not self.click_review_tab():
            print(f"{Colors.YELLOW}리뷰 탭 클릭 실패 → 건너뜀{Colors.RESET}")
            return

        # 리뷰 더보기(있는 만큼)
        self.expand_reviews_in_entry(max_clicks=self.max_clicks)

        # 리뷰 파싱
        self.parse_reviews_in_entry(restaurant_name)

    def crawl_all(self):
        print(f"{Colors.MAGENTA}=== 네이버 리뷰 크롤링 시작 (대상 {len(self.restaurants)}개) ==={Colors.RESET}")
        for i, name in enumerate(self.restaurants, 1):
            print(f"{Colors.BLUE}[{i}/{len(self.restaurants)}] {name}{Colors.RESET}")
            try:
                self.crawl_one(name)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"{Colors.RED}오류(건너뜀): {e}{Colors.RESET}")
                traceback.print_exc()
            time.sleep(0.8)  # 서버 부담 완화

        # 저장
        self.save_to_excel()
        # 필요 시 CSV도 함께
        # self.save_to_csv()

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
        print(f"{Colors.GREEN}브라우저 종료{Colors.RESET}")


if __name__ == "__main__":
    # headless=False로 먼저 눈으로 확인 후, 안정되면 True로 변경 추천
    crawler = NaverMapReviewCrawler(headless=False, max_clicks=30, wait_sec=15)
    try:
        crawler.crawl_all()
    except KeyboardInterrupt:
        print(f"{Colors.YELLOW}\n사용자에 의해 중단됨{Colors.RESET}")
    finally:
        crawler.close()
