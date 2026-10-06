from urllib.parse import urlparse

class ServiceError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status

VERDICTS = {'Αντικρούεται', 'Επιβεβαιώνεται', 'Δεν επαληθεύτηκε', 'Μερικώς σωστό / χρειάζεται πλαίσιο'}

def safe_url(uri):
    try:
        parsed = urlparse(uri)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (TypeError, ValueError):
        return False


SCHEMA = {
    'type': 'object', 'required': ['claims', 'corrected_answer', 'uncertainties', 'human_review', 'coverage'],
    'properties': {
        'claims': {'type': 'array', 'maxItems': 5, 'items': {
            'type': 'object', 'required': ['claim_id', 'claim', 'verdict', 'reason', 'support_ids', 'correction'],
            'properties': {
                'claim_id': {'type': 'integer'},
                'claim': {'type': 'string'}, 'verdict': {'type': 'string', 'enum': sorted(VERDICTS)},
                'reason': {'type': 'string'}, 'support_ids': {'type': 'array', 'items': {'type': 'integer'}},
                'correction': {'type': 'string'},
            },
        }},
        'corrected_answer': {'type': 'string'}, 'coverage': {'type': 'string'},
        'uncertainties': {'type': 'array', 'items': {'type': 'string'}},
        'human_review': {'type': 'array', 'items': {'type': 'string'}},
    },
}


def validate_result(value, grounding, planned_claims):
    if not isinstance(value, dict):
        raise ServiceError('Μη έγκυρη δομή αξιολόγησης. Ο έλεγχος δεν ολοκληρώθηκε.')
    claims = value.get('claims')
    if not isinstance(claims, list) or len(claims) != len(planned_claims) or not claims:
        raise ServiceError('Μη έγκυρος αριθμός ισχυρισμών. Ο έλεγχος δεν ολοκληρώθηκε.')
    for field in ('corrected_answer', 'coverage'):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ServiceError('Ελλιπής αξιολόγηση. Ο έλεγχος δεν ολοκληρώθηκε.')
    for field in ('uncertainties', 'human_review'):
        if not isinstance(value.get(field), list) or not all(isinstance(x, str) for x in value[field]):
            raise ServiceError('Μη έγκυρες εκκρεμότητες. Ο έλεγχος δεν ολοκληρώθηκε.')
    sources = {s['id']: s for s in grounding['sources']}
    supports = grounding['supports']
    expected = {c['claim_id']: c['claim'] for c in planned_claims}
    seen = set()
    for row in claims:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('claim','verdict','reason','correction')) or row['verdict'] not in VERDICTS:
            raise ServiceError('Μη έγκυρος ισχυρισμός. Ο έλεγχος δεν ολοκληρώθηκε.')
        claim_id = row.get('claim_id')
        if type(claim_id) is not int or claim_id not in expected or claim_id in seen or row['claim'] != expected[claim_id]:
            raise ServiceError('Η αξιολόγηση άλλαξε, παρέλειψε ή επανέλαβε αρχικό ισχυρισμό.')
        seen.add(claim_id)
        ids = row.get('support_ids')
        if not isinstance(ids, list) or any(type(i) is not int or not 1 <= i <= len(supports) for i in ids):
            raise ServiceError('Η αξιολόγηση αναφέρει τεκμήριο που δεν επιστράφηκε από το την αναζήτηση. Ο έλεγχος δεν ολοκληρώθηκε.')
        if any(supports[i - 1]['claim_id'] != claim_id for i in ids):
            row.update(verdict='Δεν επαληθεύτηκε',
                       reason='Η αξιολόγηση συνέδεσε τον ισχυρισμό με τεκμήριο άλλου ισχυρισμού. Δεν υπάρχει έγκυρη επαλήθευση.',
                       correction='Δεν προτείνεται διόρθωση χωρίς επαρκή τεκμηρίωση.',
                       support_ids=[])
            ids=[]
        if row['verdict'] != 'Δεν επαληθεύτηκε' and not ids:
            raise ServiceError('Ισχυρισμός χωρίς επαρκές τεκμήριο παρουσιάστηκε ως ελεγμένος. Ο έλεγχος δεν ολοκληρώθηκε.')
        # Links and titles come only from search results, never from model JSON.
        source_ids = sorted({s for i in ids for s in supports[i - 1]['source_ids']})
        row['sources'] = [sources[i] for i in source_ids]
        row['evidence'] = [supports[i - 1]['text'] for i in ids]
    claims.sort(key=lambda row: row['claim_id'])
    return value

