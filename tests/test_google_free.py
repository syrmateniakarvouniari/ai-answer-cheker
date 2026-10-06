import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from google.genai import types,errors
import gemini_service as service
from evidence import ServiceError


def response(value):
    return types.GenerateContentResponse(candidates=[types.Candidate(finish_reason='STOP',content=types.Content(parts=[types.Part(text=json.dumps(value))]))])


def plan():return {'claims':[{'claim':'Fixture claim','query':'official fixture query'}],'coverage':'One claim'}
def result():return {'claims':[{'claim_id':1,'claim':'Fixture claim','verdict':'Επιβεβαιώνεται','reason':'Fixture evidence','support_ids':[1],'correction':'Fixture correction'}], 'corrected_answer':'Fixture answer','coverage':'One claim','uncertainties':[],'human_review':[]}
def audit(supported=True,quote='Fixture evidence'):
    return {'checks':[{'claim_id':1,'supported':supported,'quote':quote,'support_id':1,'reason':'Evidence review'}]}
def search(query):return [{'title':'Fixture source','href':'https://example.org/source','body':'Fixture evidence'}]


class FakeModels:
    def __init__(self,values):self.values=iter(values);self.calls=[]
    def generate_content(self,**kwargs):
        self.calls.append(kwargs);value=next(self.values)
        if isinstance(value,Exception):raise value
        return value


class Tests(unittest.TestCase):
    def setUp(self):
        self.sleep_patch=patch.object(service.time,'sleep');self.sleep_patch.start();self.addCleanup(self.sleep_patch.stop)
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(service,'ROOT',Path(self.temp.name));self.patch.start()
        self.env=Path(self.temp.name)/'.env';self.env.write_text('GEMINI_API_KEY=fixture-secret\nGEMINI_MODEL=arbitrary-selected-model\nGEMINI_FREE_TIER_CONFIRMED=true\n')
        self.request={'instructions':'Fixed instructions','data':{'question':'x','answer':'y'}}
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def call(self,values,searcher=search):
        self.models=FakeModels(values)
        return service.evaluate(self.request,client=SimpleNamespace(models=self.models),searcher=searcher)
    def test_selected_model_and_actual_search_seam(self):
        queries=[]
        def searcher(query):queries.append(query);return search(query)
        value=self.call([response(plan()),response(result()),response(audit())],searcher)
        self.assertEqual(queries,['official fixture query'])
        self.assertTrue(all(c['model']=='arbitrary-selected-model' for c in self.models.calls))
        self.assertTrue(all(c['config'].tools is None for c in self.models.calls))
        self.assertEqual(value['claims'][0]['sources'][0]['url'],'https://example.org/source')
        self.assertIn('αποσπάσματα',value['limitations']);self.assertTrue(value['search_verified'])
    def test_probe_no_search(self):
        models=FakeModels([types.GenerateContentResponse(candidates=[types.Candidate(finish_reason='STOP',content=types.Content(parts=[types.Part(text='OK')]))])])
        value=service.probe_connection(SimpleNamespace(models=models))
        self.assertIn('λειτούργησε',value['message']);self.assertEqual(len(models.calls),1)
    def test_probe_error_keeps_code(self):
        for code in (401,403,404):
            models=FakeModels([errors.APIError(code,{'error':{'message':'fixture-secret'}})])
            with self.assertRaises(ServiceError) as ctx:service.probe_connection(SimpleNamespace(models=models))
            self.assertIn(str(code),str(ctx.exception));self.assertNotIn('fixture-secret',str(ctx.exception))
    def test_confirmation_and_model_required(self):
        for config in ('','GEMINI_API_KEY=x\n','GEMINI_API_KEY=x\nGEMINI_FREE_TIER_CONFIRMED=true\n'):
            self.env.write_text(config)
            with self.assertRaises(ServiceError):service.settings()
    def test_search_failure_not_success(self):
        def broken(query):raise RuntimeError('fixture-secret')
        value=self.call([response(plan())],broken)
        self.assertFalse(value['search_verified']);self.assertFalse(value['search_complete'])
        self.assertEqual(value['claims'][0]['verdict'],'Δεν επαληθεύτηκε')
        self.assertNotIn('fixture-secret',str(value));self.assertEqual(len(self.models.calls),1)
    def test_empty_results(self):
        value=self.call([response(plan())],lambda q:[])
        self.assertEqual(value['search_status'][0]['status'],'empty')
        self.assertFalse(value['search_verified'])
    def test_bad_link_excluded(self):
        value=self.call([response(plan())],lambda q:[{'href':'javascript:x','body':'x'}])
        self.assertEqual(value['sources'],[])
    def test_unverified_can_have_no_evidence(self):
        value=result();value['claims'][0]['verdict']='Δεν επαληθεύτηκε';value['claims'][0]['support_ids']=[]
        checked=self.call([response(plan()),response(value)])
        self.assertEqual(checked['claims'][0]['sources'],[])
    def test_invented_evidence(self):
        for ids in ([99],[]):
            value=result();value['claims'][0]['support_ids']=ids
            with self.assertRaises(ServiceError):self.call([response(plan()),response(value)])
    def test_no_claims(self):
        value=plan();value['claims']=[]
        with self.assertRaises(ServiceError) as ctx:self.call([response(value)])
        self.assertEqual(ctx.exception.status,422)
    def test_six_claims(self):
        value=plan();value['claims']*=6
        with self.assertRaises(ServiceError):self.call([response(value)])
    def test_invalid_model_json(self):
        value=types.GenerateContentResponse(candidates=[types.Candidate(finish_reason='STOP',content=types.Content(parts=[types.Part(text='invalid')]))])
        with self.assertRaises(ServiceError):self.call([value])
    def test_quota_no_retry_or_fallback(self):
        with self.assertRaises(ServiceError) as ctx:self.call([errors.APIError(429,{'error':{'message':'fixture-secret'}})])
        self.assertEqual(ctx.exception.status,429);self.assertEqual(len(self.models.calls),1)
    def test_empty_changed_and_duplicate_final_claims_rejected(self):
        for rows in ([],[dict(result()['claims'][0],claim='Changed')],result()['claims']*2,
                     [dict(result()['claims'][0],claim_id=True)]):
            value=result();value['claims']=rows
            with self.subTest(rows=rows),self.assertRaises(ServiceError):
                self.call([response(plan()),response(value)])

    def test_missing_and_duplicate_claim_ids_rejected(self):
        p=plan();p['claims'].append({'claim':'Second claim','query':'second'})
        for rows in (result()['claims'],result()['claims']*2):
            value=result();value['claims']=rows
            with self.assertRaises(ServiceError):self.call([response(p),response(value)])

    def test_wrong_claim_evidence_rejected(self):
        p=plan();p['claims'].append({'claim':'Second claim','query':'second'})
        value=result();value['claims'].append(dict(value['claims'][0],claim_id=2,claim='Second claim'))
        with self.assertRaises(ServiceError):self.call([response(p),response(value)])

    def test_retry_recovers(self):
        calls=[]
        def flaky(q):
            calls.append(q)
            if len(calls)==1:raise ConnectionError('secret')
            return search(q)
        value=self.call([response(plan()),response(result()),response(audit())],flaky)
        self.assertEqual(len(calls),2);self.assertTrue(value['search_complete'])

    def test_partial_search_keeps_successful_claim(self):
        p=plan();p['claims'].append({'claim':'Second claim','query':'second'})
        value=self.call([response(p),response(result()),response(audit())],lambda q:[] if q=='second' else search(q))
        self.assertTrue(value['search_verified']);self.assertFalse(value['search_complete'])
        self.assertEqual([r['verdict'] for r in value['claims']],['Επιβεβαιώνεται','Δεν επαληθεύτηκε'])
        self.assertEqual(value['claims'][1]['sources'],[])

    def test_failed_audit_or_invented_quote_downgrades(self):
        for review in (audit(False),audit(True,'invented quote')):
            value=self.call([response(plan()),response(result()),response(review)])
            row=value['claims'][0]
            self.assertEqual(row['verdict'],'Δεν επαληθεύτηκε')
            self.assertEqual(row['sources'],[]);self.assertEqual(row['support_ids'],[])
            self.assertNotIn('Fixture answer',value['corrected_answer'])
            self.assertNotIn('Fixture correction',value['corrected_answer'])

    def test_incomplete_audit_rejected(self):
        with self.assertRaises(ServiceError):self.call([response(plan()),response(result()),response({'checks':[]})])

if __name__=='__main__':unittest.main()
