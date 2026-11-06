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
