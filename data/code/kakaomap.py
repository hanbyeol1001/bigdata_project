from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import pandas as pd

def search_and_extract_reviews(driver, place_name):
    """
    주어진 장소 이름을 검색하고, 첫 번째 검색 결과의 리뷰를 추출합니다.
    :param driver: Selenium WebDriver 객체.
    :param place_name: 검색할 장소 이름 (문자열).
    :return: 추출된 리뷰 데이터(리스트) 또는 None.
    """
    try:
        # 검색창 찾기 및 초기화
        search_box = driver.find_element(By.ID, "search.keyword.query")
        search_box.clear()
        search_box.send_keys(place_name)
        
        try:
            # 먼저 표준 Selenium 클릭을 시도합니다.
            # 이 방식이 가장 일반적이고 권장되는 방법입니다.
            search_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "search.keyword.submit"))
            )
            search_button.click()
        except:
            # 표준 클릭이 가로막히면 JavaScript를 사용하여 강제 클릭합니다.
            print("표준 클릭이 실패했습니다. JavaScript로 재시도합니다.")
            search_button = driver.find_element(By.ID, "search.keyword.submit")
            driver.execute_script("arguments[0].click();", search_button)

        # 첫 번째 검색 결과의 상세정보 탭으로 이동
        # 첫 번째 항목의 XPath를 찾아 클릭. XPath는 1부터 시작합니다.
        detail_link_xpath = '//*[@id="info.search.place.list"]/li[1]/div[5]/div[4]/a[1]'
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".placelist"))
            )

        # 첫 번째 검색 결과 아이템을 찾습니다.
        first_result_item = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="info.search.place.list"]/li[1]'))
            )

        # 이제 '상세보기' 링크를 더 안정적으로 찾을 수 있습니다.
        # 이전 XPath에서 문제가 발생할 수 있으므로, 상대적인 선택자를 사용해봅니다.
        detail_link = first_result_item.find_element(By.CSS_SELECTOR, '.moreview') # '.moreview'는 '상세보기' 버튼의 클래스입니다.
        detail_link.send_keys(Keys.ENTER)
        
        # 새 탭으로 전환
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(2)
        
        # 리뷰 탭 클릭 (필요시)
        try:
            review_tab = driver.find_element(By.CSS_SELECTOR, 'a[href="#review"]')
            review_tab.click()
            time.sleep(2)
        except:
            # 리뷰 탭이 없을 경우
            print(f"'{place_name}'의 리뷰 탭을 찾을 수 없습니다.")
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            return None

        # 리뷰 추출
        reviews = []
        # 15초 동안 ".list_evaluation > li" 클래스를 가진 요소가 나타날 때까지 기다립니다.
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.list_evaluation > li'))
            )
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')

            review_items = soup.select('.list_evaluation > li')
        except:
            # 리뷰가 아예 없거나 로딩되지 않은 경우
            print(f"'{place_name}'의 리뷰를 찾을 수 없습니다. (리뷰가 없거나 로딩되지 않음)")
            return []

        if len(review_items) == 0:
            print(f"'{place_name}'에는 리뷰가 없습니다. (요소는 존재하지만 비어있음)")
            return []

        for item in review_items:
            try:
                # 리뷰 텍스트
                review_text = item.select_one('.txt_comment > span').get_text(strip=True)
                # 별점
                rating_score = item.select_one('.num_rate').get_text(strip=True)
                # 작성 날짜
                date_text = item.select_one('.info_info > span.time').get_text(strip=True)

                reviews.append({
                    "식당이름": place_name,
                    "별점": rating_score,
                    "작성날짜": date_text,
                    "리뷰텍스트": review_text
                })
            except Exception as e:
                print(f"리뷰 추출 중 오류 발생: {e}")
                continue
        

        # 새 탭 닫고 원래 탭으로 돌아가기
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        time.sleep(1)
        
        return reviews
    
    except Exception as e:
        print(f"'{place_name}' 검색 또는 추출 중 오류 발생: {e}")
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return None


def main():
    # WebDriver 옵션 설정
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # WSL에 설치된 크롬 바이너리 경로 설정
    options.binary_location = '/usr/bin/google-chrome'

    # WebDriver-manager로 드라이버 자동 설치 및 실행
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    # 검색할 식당 목록 (10개)
    restaurant_list = ["성화해장국 인하점"]
    
    # WebDriver 초기화
    driver = webdriver.Chrome()
    driver.get("https://map.kakao.com/")
    time.sleep(2)

    all_reviews = []
    
    for restaurant in restaurant_list:
        print(f"'{restaurant}'의 리뷰를 수집 중...")
        reviews_for_restaurant = search_and_extract_reviews(driver, restaurant)
        if reviews_for_restaurant:
            all_reviews.extend(reviews_for_restaurant)
    
    # 드라이버 종료
    driver.quit()
    
    # 데이터프레임 생성
    df = pd.DataFrame(all_reviews)
    print(df)

    # 결과를 XLSX 파일로 저장
    # try:
    #     df.to_excel("restaurant_reviews.xlsx", index=False)
    #     print("모든 리뷰가 'restaurant_reviews.xlsx' 파일로 저장되었습니다.")
    # except Exception as e:
    #     print(f"파일 저장 중 오류 발생: {e}")

if __name__ == "__main__":
    main()