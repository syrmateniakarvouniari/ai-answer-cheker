"""Explicit search provider selection. Credentials never leave the server."""
import httpx
from evidence import ServiceError, safe_url


class SearchError(ServiceError):
    def __init__(self, message, status=502, retryable=False):
        super().__init__(message, status)
        self.retryable = retryable


def tavily_search(query, key, post=None, depth="basic"):
    post = post or httpx.post
    try:
        response = post(
            'https://api.tavily.com/search',
            headers={'Authorization': 'Bearer ' + key},
            json={'query': query, 'search_depth': depth, 'auto_parameters': False,
                  'max_results': 5, 'include_raw_content': 'text',
                  'include_answer': False, 'include_images': False},
            timeout=15, follow_redirects=False,
        )
    except httpx.TimeoutException:
        raise SearchError('Το Tavily άργησε να απαντήσει.', 504, True) from None
    except httpx.TransportError:
        raise SearchError('Δεν ήταν δυνατή η σύνδεση με το Tavily.', 502, True) from None
    code = response.status_code
    messages = {
        400: 'Το Tavily απέρριψε το ερώτημα αναζήτησης.',
        401: 'Το Tavily απέρριψε το API key. Έλεγξε το TAVILY_API_KEY στο .env.',
        403: 'Το Tavily αρνήθηκε την πρόσβαση.',
        422: 'Το Tavily απέρριψε τη μορφή του αιτήματος.',
        429: 'Το Tavily περιόρισε τον ρυθμό αιτημάτων. Δοκίμασε αργότερα.',
        432: 'Εξαντλήθηκε το όριο χρήσης Tavily. Δεν έγινε αναβάθμιση ή αλλαγή παρόχου.',
        433: 'Το Tavily αναφέρει όριο Pay as you go. Έλεγξε το πρόγραμμα στον λογαριασμό σου.',
    }
    if code != 200:
        raise SearchError(messages.get(code, 'Η υπηρεσία Tavily απέτυχε.'),
                          429 if code in (429, 432, 433) else 502, code >= 500)
    try:
        payload = response.json()
    except ValueError:
        raise SearchError('Μη έγκυρη απάντηση Tavily.') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        raise SearchError('Το Tavily δεν επέστρεψε έγκυρη λίστα αποτελεσμάτων.')
    results = []
    for item in payload['results'][:5]:
        if not isinstance(item, dict):
            continue
        raw = item.get('raw_content')
        has_page = isinstance(raw, str) and bool(raw.strip())
        body = raw if has_page else item.get('content')
        if not isinstance(body, str) or not body.strip():
            continue
        results.append({'href': item.get('url'), 'title': item.get('title'),
                        'body': body, 'kind': 'page_text' if has_page else 'snippet'})
    return results


def select_search(config):
    provider = (config.get('SEARCH_PROVIDER') or 'tavily').strip().lower()
    if provider == 'duckduckgo':
        return duckduckgo_search, 'DuckDuckGo μέσω DDGS'
    if provider != 'tavily':
        raise ServiceError('Το SEARCH_PROVIDER πρέπει να είναι tavily ή duckduckgo.', 503)
    key = (config.get('TAVILY_API_KEY') or '').strip()
    if not key:
        raise ServiceError('Λείπει το TAVILY_API_KEY από το τοπικό .env. Μην το στείλεις στο chat.', 503)
    if config.get('TAVILY_FREE_TIER_CONFIRMED') != 'true':
        raise ServiceError('Επιβεβαίωσε δωρεάν πρόγραμμα Tavily με απενεργοποιημένο Pay as you go και βάλε TAVILY_FREE_TIER_CONFIRMED=true στο .env.', 503)
    def search(query):
        return tavily_search(query, key)
    search.extract = lambda urls: tavily_extract(urls,key)
    search.advanced = lambda query: tavily_search(query, key, depth='advanced')
    return search, 'Tavily' 


def tavily_extract(urls, key):
    """Read at most five user-supplied public HTTPS URLs through Tavily."""
    try:
        response=httpx.post('https://api.tavily.com/extract',
            headers={'Authorization':'Bearer '+key},
            json={'urls':urls[:5],'extract_depth':'basic','format':'text'},
            timeout=20,follow_redirects=False)
        if response.status_code != 200:
            raise SearchError('Δεν ολοκληρώθηκε η ανάγνωση των συνδέσμων Tavily.',502)
        payload=response.json()
        return [{'href':item['url'],'title':'Σύνδεσμος αρχικής απάντησης',
                 'body':item['raw_content'],'kind':'page_text'}
                for item in payload.get('results',[])
                if safe_url(item.get('url')) and isinstance(item.get('raw_content'),str)
                and item['raw_content'].strip()]
    except (httpx.HTTPError,ValueError,KeyError):
        raise SearchError('Δεν ολοκληρώθηκε η ανάγνωση των συνδέσμων Tavily.',502) from None


def duckduckgo_search(query):
    from ddgs import DDGS
    return list(DDGS(timeout=12).text(query,backend='duckduckgo',max_results=5))
