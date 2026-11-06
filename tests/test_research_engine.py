"""Bounded research pipeline and evidence/citation behavior."""
import json
import threading
import unittest
from unittest.mock import patch

from babymind import research_engine


class Provider:
    def __init__(self, plan=None, report='Evidence supports the answer [1].'):
        self.plan = plan if plan is not None else json.dumps({'queries': ['alpha', 'beta']})
        self.report = report
        self.calls = []
    def complete(self, system, user):
        self.calls.append((system, user))
        return self.plan if len(self.calls) == 1 else self.report


def page(url):
    return {'url': url, 'title': 'Source title', 'text': 'Observed evidence', 'truncated': 0}


class ResearchEngineTests(unittest.TestCase):
    def test_search_and_fetch_run_in_parallel_and_pass_real_evidence_to_model(self):
        search_barrier = threading.Barrier(3, timeout=3)
        fetch_barrier = threading.Barrier(3, timeout=3)
        def search(query, limit):
            search_barrier.wait()
            return [{'url': 'https://example.com/' + query.replace(' ', '-'), 'snippet': 'NOT EVIDENCE'}]
        def fetch(url):
            fetch_barrier.wait()
            return page(url)
        provider = Provider()
        with patch('babymind.research.search_web', side_effect=search), patch('babymind.research.fetch_page', side_effect=fetch):
            result = research_engine.investigate(provider, 'original')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['sources']), 3)
        self.assertIn('Observed evidence', provider.calls[1][1])
        self.assertNotIn('NOT EVIDENCE', provider.calls[1][1])
        self.assertIn('untrusted', provider.calls[1][0].lower())
        self.assertIn('[1] Source title — https://example.com/original', research_engine.format_report(result))
        self.assertIn('not fact-checked', result['citation_check']['reason'])

    def test_partial_fetch_failure_is_visible_and_not_citable(self):
        provider = Provider(report='Supposed answer [2]')
        def search(query, limit):
            return [{'url': 'https://example.com/a'}, {'url': 'https://example.com/b'}]
        def fetch(url):
            if url.endswith('/b'): raise ValueError('blocked')
            return page(url)
        with patch('babymind.research.search_web', side_effect=search), patch('babymind.research.fetch_page', side_effect=fetch):
            result = research_engine.investigate(provider, 'original')
        self.assertEqual(result['status'], 'citation_warning')
        self.assertIn('Unknown citation numbers: 2', result['citation_check']['reason'])
        self.assertEqual(len(result['sources']), 1)
        self.assertTrue(any('blocked' in item for item in result['errors']))

    def test_no_readable_sources_never_synthesizes_from_snippets(self):
        provider = Provider(plan='invalid json')
        with patch('babymind.research.search_web', return_value=[{'url': 'https://example.com'}]), \
             patch('babymind.research.fetch_page', side_effect=ValueError('blocked')):
            result = research_engine.investigate(provider, 'original')
        self.assertEqual(result['status'], 'no_sources')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['queries'], ['original'])
        self.assertTrue(result['errors'])

    def test_citation_and_fabricated_url_warnings(self):
        for answer in ('No citations.', 'Text [9].', 'Text [1] https://invented.example/', 'x' * 13000 + '[1]'):
            with self.subTest(answer=answer[:40]):
                provider = Provider(report=answer)
                with patch('babymind.research.search_web', return_value=[{'url': 'https://example.com'}]), \
                     patch('babymind.research.fetch_page', side_effect=page):
                    result = research_engine.investigate(provider, 'test')
                self.assertFalse(result['citation_check']['valid'])

    def test_memory_is_not_sent_to_search(self):
        seen = []
        def search(query, limit):
            seen.append(query)
            return [{'url': 'https://example.com'}]
        provider = Provider()
        with patch('babymind.research.search_web', side_effect=search), patch('babymind.research.fetch_page', side_effect=page):
            research_engine.investigate(provider, 'question', memories=[{'task':'PRIVATE', 'response':'NOTE'}])
        self.assertTrue(all('PRIVATE' not in query for query in seen))
        self.assertNotIn('PRIVATE', provider.calls[0][1])
        self.assertIn('PRIVATE', provider.calls[1][1])

    def test_invalid_query_rejected_before_network_or_model(self):
        provider = Provider()
        for query in ('', 'x' * 501, None):
            with self.assertRaises(ValueError): research_engine.investigate(provider, query)
        self.assertEqual(provider.calls, [])

    def test_fair_deduped_bounded_selection_and_failures(self):
        provider = Provider()
        def search(query, limit):
            if query == 'beta': raise RuntimeError('search down')
            return [{'url': 'https://example.com/' + str(i) + query} for i in range(5)]
        with patch('babymind.research.search_web', side_effect=search), patch('babymind.research.fetch_page', side_effect=page):
            result = research_engine.investigate(provider, 'original')
        self.assertEqual(len(result['sources']), 6)
        self.assertTrue(any('search down' in error for error in result['errors']))
        self.assertIn('alpha', result['sources'][1]['url'])


class DocumentResearchTests(unittest.TestCase):
    class Provider:
        def __init__(self, output='Summary [1].'):
            self.output = output
            self.calls = []
        def complete(self, system, user):
            self.calls.append((system, user))
            return self.output

    def test_local_document_retrieval_ranks_late_match_without_network(self):
        provider = self.Provider()
        text = ('line boilerplate\n' * 350) + 'NEEDLE detail decisive evidence\n'
        with patch('babymind.research.search_web') as search, patch('babymind.research.fetch_page') as fetch:
            result = research_engine.investigate_document(provider, 'What is NEEDLE?', {'name': 'note.txt', 'content': text})
        search.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(len(provider.calls), 1)
        self.assertIn('NEEDLE detail decisive evidence', provider.calls[0][1])
        self.assertIn('untrusted', provider.calls[0][0].lower())
        self.assertEqual(result['status'], 'completed')
        self.assertLessEqual(len(result['sources']), 3)
        self.assertTrue(all('text' not in source and source['kind'] == 'document' for source in result['sources']))
        self.assertTrue(all('lines ' in source['location'] and 'characters ' in source['location'] for source in result['sources']))
        self.assertIn('note.txt', research_engine.format_report(result))
        self.assertTrue(any('omitted' in error for error in result['errors']))

    def test_bad_input_is_rejected_before_model_call(self):
        provider = self.Provider()
        invalid = [None, {}, {'name': '../secret.txt', 'content': 'a'},
                   {'name': 'note.txt\n', 'content': 'a'}, {'name': 'note.txt', 'content': ''},
                   {'name': 'note.txt', 'content': '\0'}, {'name': 'note.txt', 'content': 'é' * 6001},
                   {'name': 'note.txt', 'content': '\ud800'}, {'name': '\ud800', 'content': 'text'},
                   {'name': 'x', 'content': 'text', 'path': '/etc/passwd'}]
        for item in invalid:
            with self.subTest(item=repr(item)[:80]), self.assertRaises(ValueError):
                research_engine.investigate_document(provider, 'question', item)
        self.assertEqual(provider.calls, [])

    def test_document_citation_warnings_are_truthful(self):
        for answer in ('no citations', 'guess [99]', 'source [1] https://invented.example/'):
            with self.subTest(answer=answer):
                result = research_engine.investigate_document(self.Provider(answer), 'question', {'name':'a.txt', 'content':'evidence'})
                self.assertEqual(result['status'], 'citation_warning')
                self.assertFalse(result['citation_check']['valid'])

    def test_crlf_lines_and_optional_memory(self):
        provider = self.Provider()
        text = 'first\r\nsecond\r\nthird'
        result = research_engine.investigate_document(provider, 'question', {'name':'x.txt', 'content':text},
                                                       memories=[{'task':'preference', 'response':'brief'}])
        self.assertEqual(result['sources'][0]['location'], 'lines 1–3, characters 1–20')
        self.assertIn('preference', provider.calls[0][1])
        self.assertIn('first\\r\\nsecond', provider.calls[0][1])

    def test_single_line_truncation_offsets_are_accurate(self):
        text = 'a' * 1190 + 'marker' + 'z' * 1210
        result = research_engine.investigate_document(self.Provider(), 'marker', {'name':'x.txt', 'content':text})
        self.assertEqual(result['sources'][0]['location'], 'lines 1–1, characters 1–1200')
        self.assertEqual(result['sources'][1]['location'], 'lines 1–1, characters 1201–2400')
