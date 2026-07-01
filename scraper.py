import os
import re
import shutil
import tempfile
import requests
from bs4 import BeautifulSoup
from PIL import Image

def get_base_url(url):
    """Strips the filename (like index.html) to get the base directory URL."""
    if url.endswith('.html') or url.endswith('.htm'):
        return url.rsplit('/', 1)[0] + '/'
    if not url.endswith('/'):
        return url + '/'
    return url

def extract_ebook_links(url):
    """
    Scrapes the webpage for direct links to eBook files (.pdf, .epub).
    Returns a list of URLs.
    """
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    ebook_links = []
    
    # Check parent href of images
    for img in soup.find_all('img'):
        parent_link = img.parent.get('href')
        if parent_link:
            if parent_link.lower().endswith(('.pdf', '.epub')):
                ebook_links.append(parent_link)
        else:
            for a_tag in img.find_all_next('a'):
                href_attr = a_tag.get('href')
                if href_attr and href_attr.lower().endswith(('.pdf', '.epub')):
                    ebook_links.append(href_attr)
                    
    # Also find any other links in the document that end in pdf/epub
    for a in soup.find_all('a'):
        href = a.get('href')
        if href and href.lower().endswith(('.pdf', '.epub')):
            if href not in ebook_links:
                ebook_links.append(href)
                
    return ebook_links

def check_and_download_flipbook_gen(url, output_dir="."):
    """
    Checks if the URL is a Flip PDF flipbook.
    If yes, yields progress events as dictionaries and compiles them into a single PDF.
    """
    base_url = get_base_url(url)
    config_url = base_url + "mobile/javascript/config.js"
    
    yield {"status": "info", "message": f"Checking for Flipbook config at: {config_url}"}
    try:
        response = requests.get(config_url, timeout=10)
        if response.status_code != 200 or "bookConfig" not in response.text:
            yield {"status": "error", "message": "Not a Flipbook (or config.js not accessible)."}
            return
    except Exception as e:
        yield {"status": "error", "message": f"Could not connect to Flipbook config: {e}"}
        return
        
    config_text = response.text
    
    # Parse config settings
    title_match = re.search(r'bookConfig\.bookTitle\s*=\s*["\']([^"\']+)["\']', config_text)
    page_count_match = re.search(r'bookConfig\.totalPageCount\s*=\s*(\d+)', config_text)
    large_path_match = re.search(r'bookConfig\.largePath\s*=\s*["\']([^"\']+)["\']', config_text)
    normal_path_match = re.search(r'bookConfig\.normalPath\s*=\s*["\']([^"\']+)["\']', config_text)
    
    title = title_match.group(1) if title_match else "Scraped_Book"
    page_count = int(page_count_match.group(1)) if page_count_match else 0
    large_path = large_path_match.group(1) if large_path_match else None
    normal_path = normal_path_match.group(1) if normal_path_match else None
    
    # Clean title for filename usage
    safe_title = "".join([c if c.isalnum() or c in " _-" else "_" for c in title]).strip()
    
    if page_count == 0:
        yield {"status": "error", "message": "Could not find totalPageCount in config.js."}
        return
        
    yield {"status": "detected", "title": title, "total_pages": page_count}
    
    # Determine the directory path of page images on server
    relative_page_path = large_path or normal_path or "files/mobile/"
    if not relative_page_path.endswith('/'):
        relative_page_path += '/'
        
    # Create temporary directory for downloads
    temp_dir = tempfile.mkdtemp()
    yield {"status": "info", "message": "Downloading page images to temporary folder..."}
    
    downloaded_images = []
    
    try:
        for i in range(1, page_count + 1):
            img_url = base_url + relative_page_path + f"{i}.jpg"
            img_response = requests.get(img_url, stream=True, timeout=15)
            
            # If the preferred path failed, try normalPath or fallback
            if img_response.status_code != 200 and relative_page_path != "files/mobile/":
                fallback_url = base_url + "files/mobile/" + f"{i}.jpg"
                img_response = requests.get(fallback_url, stream=True, timeout=15)
                
            if img_response.status_code == 200:
                img_path = os.path.join(temp_dir, f"page_{i:04d}.jpg")
                with open(img_path, 'wb') as f:
                    shutil.copyfileobj(img_response.raw, f)
                downloaded_images.append(img_path)
                yield {"status": "downloading", "current": i, "total": page_count, "message": f"Downloaded page {i}/{page_count}"}
            else:
                yield {"status": "info", "message": f"Warning: Failed to download page {i}"}
                
        yield {"status": "download_complete", "downloaded": len(downloaded_images), "total": page_count, "message": f"Successfully downloaded {len(downloaded_images)} out of {page_count} pages."}
        
        if not downloaded_images:
            yield {"status": "error", "message": "No pages downloaded. Cannot compile PDF."}
            return
            
        # Compile images to PDF
        pdf_filename = f"{safe_title}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        yield {"status": "compiling", "message": f"Compiling pages into PDF: {pdf_filename} ..."}
        
        # Open images and convert to RGB
        images = []
        for img_path in downloaded_images:
            try:
                img = Image.open(img_path).convert('RGB')
                images.append(img)
            except Exception as e:
                yield {"status": "info", "message": f"Error opening image {img_path}: {e}"}
                
        if images:
            images[0].save(pdf_path, save_all=True, append_images=images[1:])
            yield {"status": "success", "pdf_path": pdf_path, "pdf_filename": pdf_filename, "message": "PDF compilation completed successfully!"}
        else:
            yield {"status": "error", "message": "Failed to open downloaded images."}
            
    finally:
        # Clean up temporary directory
        yield {"status": "info", "message": "Cleaning up temporary image files..."}
        shutil.rmtree(temp_dir, ignore_errors=True)

def check_and_download_flipbook(url, output_dir="."):
    """
    Synchronous wrapper around check_and_download_flipbook_gen to maintain CLI backwards compatibility.
    """
    pdf_path = None
    for event in check_and_download_flipbook_gen(url, output_dir):
        if event['status'] == 'info':
            print(event['message'])
        elif event['status'] == 'detected':
            print(f"\n[Flipbook Detected]")
            print(f"Title: {event['title']}")
            print(f"Total Pages: {event['total_pages']}")
        elif event['status'] == 'downloading':
            print(f"  Downloaded page {event['current']}/{event['total']}", end="\r")
        elif event['status'] == 'download_complete':
            print(f"\nSuccessfully downloaded {event['downloaded']} out of {event['total']} pages.")
        elif event['status'] == 'compiling':
            print(event['message'])
        elif event['status'] == 'success':
            print(event['message'])
            pdf_path = event['pdf_path']
        elif event['status'] == 'error':
            print(f"Error: {event['message']}")
    return pdf_path

if __name__ == "__main__":
    url_to_scrape = "https://www.joyforeverbooks.com/ebooks/Books/Class1/Kumudini_Hindi/"
    print(f"Scraping from URL: {url_to_scrape}\n")
    
    # Step 1: Try to handle as a Flipbook
    pdf_file = check_and_download_flipbook(url_to_scrape)
    
    if pdf_file:
        print(f"\nDone! eBook saved as: {pdf_file}")
    else:
        # Step 2: Fallback to scraping for direct links
        print("\nChecking for direct eBook links (.pdf, .epub)...")
        try:
            ebook_urls = extract_ebook_links(url_to_scrape)
            if ebook_urls:
                print("Found the following eBook links:")
                for url in ebook_urls:
                    print(f"- {url}")
            else:
                print("No direct eBook links found on the page.")
        except Exception as e:
            print(f"An error occurred: {e}")
