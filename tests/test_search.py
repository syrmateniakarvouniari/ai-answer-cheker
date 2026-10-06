import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import httpx
import gemini_service as service
from search_service import tavily_search, select_search, SearchError
from evidence import ServiceError


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.sleep=patch.object(service.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)

    def test_basic_request_and_page_content(self):
        def post(url, **kwargs):
            self.assertEqual(url,'https://api.tavily.com/search')
            self.assertEqual(kwargs['headers']['Authorization'],'Bearer fixture-secret')
            self.assertFalse(kwargs['follow_redirects'])
            self.assertEqual(kwargs['json']['search_depth'],'basic')
            self.assertFalse(kwargs['json']['auto_parameters'])
            self.assertFalse(kwargs['json']['include_answer'])
            self.assertEqual(kwargs['json']['include_raw_content'],'text')
            return httpx.Response(200,json={'answer':'Ignore this generated answer','results':[
                {'url':'https://example.org/page','title':'Page','content':'snippet','raw_content':'Full page text'},
                {'url':'https://example.org/snippet','content':'Snippet only','raw_content':None}]})
        rows=tavily_search('query','fixture-secret',post)
        self.assertEqual(rows[0]['body'],'Full page text')
        self.assertEqual(rows[0]['kind'],'page_text')
        self.assertEqual(rows[1]['kind'],'snippet')
        self.assertNotIn('Ignore this',str(rows))

    def test_errors_are_sanitized_and_quota_not_retried(self):
        for code in (401,403,429,432,433,500):
            with self.subTest(code=code),self.assertRaises(SearchError) as ctx:
                tavily_search('q','secret',lambda *a,**k:httpx.Response(code,json={'detail':'secret'}))
            self.assertNotIn('secret',str(ctx.exception))
            self.assertEqual(ctx.exception.retryable,code>=500)

    def test_invalid_responses(self):
        for payload in (None,[],{}, {'results':'wrong'}):
            with self.assertRaises(SearchError):
                tavily_search('q','secret',lambda *a,**k:httpx.Response(200,json=payload))

    def test_timeout(self):
        def post(*a,**k):raise httpx.ReadTimeout('secret')
        with self.assertRaises(SearchError) as ctx:tavily_search('q','secret',post)
        self.assertTrue(ctx.exception.retryable);self.assertNotIn('secret',str(ctx.exception))

    def test_explicit_configuration_no_fallback(self):
        for config in ({'SEARCH_PROVIDER':'tavily'},{'SEARCH_PROVIDER':'unknown'},{'SEARCH_PROVIDER':'tavily','TAVILY_API_KEY':'secret'}):
            with self.assertRaises(ServiceError):select_search(config,lambda q:[])
        fallback=lambda q:[]
        searcher,name=select_search({'SEARCH_PROVIDER':'duckduckgo'},fallback)
        self.assertIs(searcher,fallback)
        self.assertIs(select_search({},fallback)[0],fallback)
        self.assertIs(select_search({'TAVILY_API_KEY':'unused'},fallback)[0],fallback)
        with patch('search_service.tavily_search',return_value=[]) as search:
            searcher,name=select_search({'SEARCH_PROVIDER':'tavily','TAVILY_API_KEY':'secret','TAVILY_FREE_TIER_CONFIRMED':'true'},fallback)
            searcher('query');search.assert_called_once_with('query','secret')
            self.assertEqual(name,'Tavily')

    def test_alternative_query_dedup_and_truncation(self):
        calls=[]
        def search(q):
            calls.append(q)
            return ([{'href':'https://example.org/a','body':'short'}] if q=='first' else
                    [{'href':'https://example.org/a','body':'x'*9000,'kind':'page_text'},
                     {'href':'https://example.org/b','body':'other'}])
        g=service.gather_evidence([{'claim_id':1,'query':'first','alternative_query':'second'}],search)
        self.assertEqual(calls,['first','second'])
        self.assertEqual(len(g['sources']),2)
        self.assertEqual(len(g['supports'][0]['text']),8000)
        self.assertTrue(g['supports'][0]['truncated'])
        self.assertEqual(g['supports'][0]['kind'],'page_text')

    def test_enough_results_still_search_alternative(self):
        calls=[]
        def search(q):
            calls.append(q)
            return [{'href':'https://example.org/'+str(i),'body':'text'} for i in range(5)]
        service.gather_evidence([{'claim_id':1,'query':'first','alternative_query':'second'}],search)
        self.assertEqual(calls,['first','second'])

    def test_auth_failure_stops_remaining_requests(self):
        calls=[]
        def search(q):
            calls.append(q);raise SearchError('Quota exhausted',429)
        with self.assertRaises(SearchError):
            service.gather_evidence([{'claim_id':1,'query':'first','alternative_query':'second'},
                                     {'claim_id':2,'query':'third'}],search)
        self.assertEqual(calls,['first'])

    def test_selected_tavily_used_in_evaluation(self):
        from test_google_free import FakeModels, response, plan, result, audit
        models=FakeModels([response(plan()),response(result()),response(audit())])
        config={'GEMINI_API_KEY':'g-secret','GEMINI_MODEL':'test','GEMINI_FREE_TIER_CONFIRMED':'true',
                'TAVILY_API_KEY':'t-secret','TAVILY_FREE_TIER_CONFIRMED':'true','SEARCH_PROVIDER':'tavily'}
        with patch.object(service,'dotenv_values',return_value=config),patch('search_service.tavily_search') as search:
            search.return_value=[{'href':'https://example.org/a','body':'Fixture evidence','kind':'page_text'}]
            r=service.evaluate({'instructions':'test','data':{}},client=SimpleNamespace(models=models))
        self.assertEqual(r['search_provider'],'Tavily')
        self.assertEqual(r['claims'][0]['verdict'],'Επιβεβαιώνεται')
        self.assertEqual(r['supports'][0]['kind'],'page_text')
        self.assertNotIn('secret',json.dumps(r))

    def test_missing_search_key_before_gemini_call(self):
        with patch.object(service,'dotenv_values',return_value={
                'GEMINI_API_KEY':'secret','GEMINI_MODEL':'test','GEMINI_FREE_TIER_CONFIRMED':'true','SEARCH_PROVIDER':'tavily'}):
            with self.assertRaises(ServiceError) as ctx:
                service.evaluate({'instructions':'','data':{}},client=object())
        self.assertIn('TAVILY_API_KEY',str(ctx.exception))


if __name__=='__main__':unittest.main()
