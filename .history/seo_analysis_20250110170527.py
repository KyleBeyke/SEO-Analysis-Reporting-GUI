import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import Counter
import re
import pandas as pd
import nltk
from nltk.corpus import stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
import matplotlib.pyplot as plt
from datetime import datetime
import os

nltk.download('stopwords')

# Stopwords for SEO analysis
STOPWORDS = set(stopwords.words('english'))
SEO_STOPWORDS = STOPWORDS.union({'click', 'learn', 'read', 'know', 'find', 'home', 'page', 'contact', 'image', 'photo'})

# Directory for logs
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
ERROR_LOG = os.path.join(LOG_DIR, "error_log.txt")


def scrape_internal_links(base_url, max_pages=50):
    visited = set()
    to_visit = set([base_url])

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.pop()
        if current_url in visited:
            continue

        print(f"Scraping: {current_url}")
        try:
            response = requests.get(current_url, timeout=5)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            visited.add(current_url)

            for link in soup.find_all('a', href=True):
                href = urljoin(base_url, link['href'])
                if is_internal_link(href, base_url):
                    to_visit.add(href)
        except Exception as e:
            log_error(f"Error scraping {current_url}: {e}")

    return visited


def is_internal_link(url, base_url):
    base_domain = urlparse(base_url).netloc
    return urlparse(url).netloc == base_domain


def extract_keywords_and_images(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            return [], [], []

        soup = BeautifulSoup(response.text, 'html.parser')

        keywords = []
        missing_alt = []
        image_keywords = []

        # Extract keywords from SEO-relevant elements
        if soup.title:
            keywords.extend(clean_and_tokenize(soup.title.string))

        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            keywords.extend(clean_and_tokenize(meta_desc['content']))

        for tag in ['h1', 'h2', 'h3']:
            for heading in soup.find_all(tag):
                keywords.extend(clean_and_tokenize(heading.get_text(strip=True)))

        for anchor in soup.find_all('a', href=True):
            if anchor.get_text():
                keywords.extend(clean_and_tokenize(anchor.get_text(strip=True)))

        # Extract image-related keywords
        for img in soup.find_all('img'):
            if 'alt' in img.attrs and img['alt'].strip():
                keywords.extend(clean_and_tokenize(img['alt']))
                image_keywords.extend(clean_and_tokenize(img['alt']))
            else:
                missing_alt.append(img.get('src', 'Unknown Source'))

        return keywords, image_keywords, missing_alt
    except Exception as e:
        log_error(f"Error extracting keywords from {url}: {e}")
        return [], [], []


def clean_and_tokenize(text):
    text = text.lower()
    words = re.findall(r'\b[a-z]{3,}\b', text)  # Extract words with 3+ letters
    return [word for word in words if word not in SEO_STOPWORDS]


def compute_tfidf(all_texts):
    vectorizer = TfidfVectorizer(stop_words='english', max_features=100)
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    feature_names = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.sum(axis=0).A1
    return sorted(zip(feature_names, scores), key=lambda x: x[1], reverse=True)


def visualize_top_keywords(keywords):
    df = pd.DataFrame(keywords, columns=["Keyword", "Score"])
    df = df.head(20)

    # Bar chart
    plt.figure(figsize=(10, 6))
    plt.bar(df["Keyword"], df["Score"], color='skyblue')
    plt.title("Top 20 Keywords")
    plt.xticks(rotation=45, ha='right')
    plt.ylabel("Score")
    plt.tight_layout()
    plt.show()

    # Pie chart
    plt.figure(figsize=(8, 8))
    plt.pie(df["Score"], labels=df["Keyword"], autopct='%1.1f%%', startangle=140)
    plt.title("Top Keyword Proportions")
    plt.tight_layout()
    plt.show()


def log_error(message):
    with open(ERROR_LOG, "a") as log_file:
        log_file.write(f"{datetime.now()}: {message}\n")


def analyze_keywords(base_url, max_pages=50):
    start_time = datetime.now()

    internal_links = scrape_internal_links(base_url, max_pages)

    all_texts = []
    all_keywords = []
    all_image_keywords = []
    all_missing_alts = []

    page_keywords = {}

    for url in internal_links:
        print(f"Analyzing keywords on: {url}")
        keywords, image_keywords, missing_alt = extract_keywords_and_images(url)
        all_keywords.extend(keywords)
        all_image_keywords.extend(image_keywords)
        all_missing_alts.extend(missing_alt)
        all_texts.append(' '.join(keywords))

        # Store page-level keywords
        page_keywords[url] = Counter(keywords).most_common(5)

    # TF-IDF Analysis
    tfidf_keywords = compute_tfidf(all_texts)

    # Results and Visualization
    print("\nTop 20 Keywords by TF-IDF:")
    for word, score in tfidf_keywords[:20]:
        print(f"{word}: {score:.2f}")

    visualize_top_keywords(tfidf_keywords)

    # Missing alt attributes
    if all_missing_alts:
        print("\nImages with Missing alt Attributes:")
        for src in all_missing_alts:
            print(src)

    # Page-level keyword insights
    print("\nTop Keywords by Page:")
    for url, keywords in page_keywords.items():
        print(f"{url}: {keywords}")

    # Save results to CSV
    pd.DataFrame(tfidf_keywords, columns=["Keyword", "Score"]).to_csv("seo_keyword_analysis.csv", index=False)
    print("\nResults saved to 'seo_keyword_analysis.csv'.")

    end_time = datetime.now()
    runtime = end_time - start_time
    print(f"\nScript completed in {runtime}.")


def main():
    base_url = "https://kallicollective.com" #input("Enter the base URL: ").strip()
    max_pages = 500 #int(input("Enter the maximum number of pages to scrape: ").strip())
    analyze_keywords(base_url, max_pages)


if __name__ == "__main__":
    main()
