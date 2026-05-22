import re

def test():
    try:
        with open('bing_response.html', 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception as e:
        print(f"Could not read file: {e}")
        return

    # Let's inspect BING_RESULT_RE
    regex = re.compile(
        r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?<h2[^>]*>\s*<a[^>]+href="(?P<href>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.S | re.I,
    )
    
    matches = list(regex.finditer(html))
    print(f"Matches count: {len(matches)}")
    for i, m in enumerate(matches[:5]):
        print(f"Match {i+1}:")
        print(f"  href: {m.group('href')}")
        print(f"  title: {m.group('title')[:60]}")

    if not matches:
        print("Checking for any b_algo elements in the HTML...")
        b_algo_matches = re.findall(r'class="[^"]*b_algo[^"]*"', html)
        print(f"Found {len(b_algo_matches)} class entries containing 'b_algo'")
        
        # Check if there are any <li class="b_algo">
        li_b_algo = re.findall(r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>', html)
        print(f"Found {len(li_b_algo)} <li> tags with 'b_algo' in class")
        if li_b_algo:
            print("First few:")
            for tag in li_b_algo[:3]:
                print(f"  {tag}")

        # Let's check search results anchors
        print("\nChecking any h2 search result headers...")
        h2_tags = re.findall(r'<h2[^>]*>.*?</h2>', html, re.S | re.I)
        print(f"Found {len(h2_tags)} <h2> tags")
        for tag in h2_tags[:5]:
            print(f"  {tag[:120]}")

if __name__ == "__main__":
    test()
