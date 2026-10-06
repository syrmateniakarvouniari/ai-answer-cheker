import unittest
from evidence import validate_result

class AssignmentTests(unittest.TestCase):
    def test_cross_claim_support_downgrades_only_affected_claim(self):
        planned=[{'claim_id':1,'claim':'First'}, {'claim_id':2,'claim':'Second'}]
        grounding={'sources':[{'id':1,'url':'https://example.org'}],
                   'supports':[{'claim_id':1,'source_ids':[1],'text':'First evidence'},
                               {'claim_id':2,'source_ids':[1],'text':'Second evidence'}]}
        value={'claims':[{'claim_id':i,'claim':claim,'verdict':'Επιβεβαιώνεται',
                         'reason':'Evidence','correction':'Correction','support_ids':[1]}
                         for i,claim in [(1,'First'),(2,'Second')]],
               'corrected_answer':'Answer','coverage':'Both','uncertainties':[],'human_review':[]}
        checked=validate_result(value,grounding,planned)
        self.assertEqual(checked['claims'][0]['verdict'],'Επιβεβαιώνεται')
        bad=checked['claims'][1]
        self.assertEqual(bad['verdict'],'Δεν επαληθεύτηκε')
        self.assertEqual(bad['support_ids'],[])
        self.assertEqual(bad['sources'],[])
        self.assertEqual(bad['evidence'],[])
