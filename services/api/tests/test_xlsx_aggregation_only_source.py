"""WO-N9 작업 7: 질문 색인 한도를 넘는 XLSX는 처리 실패가 아니라 '집계 전용' 소스로 완료한다."""
from __future__ import annotations

import copy
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from daon2_user_api.document_index_postgres import IndexedEvidenceChunk, PostgresDocumentIndex
from daon2_user_api.document_processing import DocumentProcessingContext, DocumentProcessingService
from daon2_user_api.document_processing_postgres import PostgresDocumentProcessingRepository
from daon2_user_api.document_processing_worker import DocumentProcessingWorker
from daon2_user_api.document_understanding_adapter import DocumentUnderstandingError
from daon2_user_api.question_answering_postgres import QuestionContext, ReadyQuestionSource
from daon2_user_api.question_answering_service import (
    QuestionAnsweringError, QuestionAnsweringService, QuestionInputSource,
)
from daon2_user_api.source_ingest import SourceRejected
from daon2_user_api.studio_source_reader import StudioSourceReader
from daon2_user_api.studio_workspace import StudioContext, StudioError
from daon2_user_api.workspace_model_defaults import ResolvedModel
from daon2_user_api.xlsx_source import XlsxIndexLimitExceeded, read_xlsx

from test_document_processing import Adapter, AdapterFactory
from test_document_processing_postgres import FakeCloudStore, FakeObjectStorage
from test_document_processing_worker import FakeIndex, FakeQueue, job
import test_document_index_postgres as index_fixture
from test_question_answering_service import (
    FakeCredential, FakeEgress, FakeIndex as QuestionIndex, FakeProviderSettings, FakeRepository, FakeTransport,
)
from test_xlsx_document_understanding import Transport, original
from test_xlsx_source import parts, zipped

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
NOW = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
AGG_MESSAGE = '이 표는 데이터 집계에만 쓸 수 있습니다'


def large_xlsx(count=3000, *, extra=None):
    sheet = '<sheetData>' + ''.join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, count + 1)) + '</sheetData>'
    entries = parts([('매출', sheet, 'visible')])
    if extra:
        extra(entries)
    return zipped(entries)


class Resolver:
    def __init__(self):
        self.calls = []

    @contextmanager
    def resolve(self, context, capability):
        self.calls.append(capability)
        yield ResolvedModel('ollama-1', 'OLLAMA', 'llama3.2:3b', capability, 'https://ollama.example', 0, 1, 1, 'server_internal', 'provider', True, None)


class ExplodingXlsxAdapter:
    def understand(self, *args, **kwargs):
        raise AssertionError('집계 전용 XLSX는 질문 색인용 모델 이해를 부르지 않는다')


def processing_fixture(content):
    store = FakeCloudStore(); storage = FakeObjectStorage()
    store.connection.filename = 'sales.xlsx'; store.connection.content_type = XLSX
    store.connection.content = storage.content = content
    store.connection.states = {'ProcessingRun': 'vision_llm_understanding', 'Source': 'processing'}
    store.connection.versions = {'ProcessingRun': 2, 'Source': 3}
    return store, storage


def inserted(store, table):
    return [params[4].obj for sql, params in store.connection.statements if sql.startswith(f'INSERT INTO {table}')]


class XlsxAggregationOnlySourceTests(unittest.TestCase):
    def setUp(self):
        self.context = DocumentProcessingContext('tenant-cp3', 'workspace-cp3', 'actor-cp3', 'trace-cp3', 'policy-v1')

    def test_index_limit_exception_is_only_for_question_index_limits(self):
        with self.assertRaises(XlsxIndexLimitExceeded) as raised:
            read_xlsx(large_xlsx())
        self.assertIsInstance(raised.exception, SourceRejected)
        self.assertEqual(raised.exception.args[0] if raised.exception.args else getattr(raised.exception, 'code', None), 'UNSUPPORTED_FORMAT')
        # 32 KB 구조 한도(셀 수와 별개)도 같은 예외다.
        with self.assertRaises(XlsxIndexLimitExceeded):
            read_xlsx(zipped(parts([('긴 글', '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>' + '요' * 6000 + '</t></is></c></row></sheetData>', 'visible')])))
        for corrupt in (b'PK\x03\x04broken', b'not a zip'):
            with self.subTest(corrupt=corrupt), self.assertRaises(SourceRejected) as other:
                read_xlsx(corrupt)
            self.assertNotIsInstance(other.exception, XlsxIndexLimitExceeded)

    def test_large_xlsx_completes_as_aggregation_only(self):
        content = large_xlsx()
        store, storage = processing_fixture(content)
        resolver = Resolver(); queue = FakeQueue(job())
        service = DocumentProcessingService(PostgresDocumentProcessingRepository(store, storage), resolver,
                                            AdapterFactory(Adapter()), xlsx_adapter=ExplodingXlsxAdapter())
        results = []
        original_process = service.process_existing
        service.process_existing = lambda *a, **k: results.append(original_process(*a, **k)) or results[-1]
        worker = DocumentProcessingWorker('worker-cp3', queue, service, FakeIndex(queue.events), clock=lambda: NOW)
        self.assertTrue(worker.run_once())
        self.assertEqual(queue.events[-1], ('complete', 'run-cp3'))
        self.assertEqual(store.connection.states['ProcessingRun'], 'completed')
        self.assertEqual(resolver.calls, [])
        (result,) = results
        self.assertEqual(result.status, 'ready')
        self.assertEqual(result.parser.cell_evidence, ())
        self.assertEqual(result.semantic.key_facts, ())
        self.assertEqual(result.lineage['aggregation_only'], 'true')
        self.assertEqual(result.lineage['source_format'], 'xlsx')
        (understanding,) = inserted(store, 'understanding_results')
        self.assertEqual(understanding['lineage']['aggregation_only'], 'true')
        self.assertEqual(understanding['parser_validation']['cell_evidence'], [])
        self.assertEqual((understanding['parser_validation']['text'], understanding['parser_validation']['markdown']), ('', ''))
        (extraction,) = inserted(store, 'extraction_evidence')
        # 색인: 근거 구간 0개, 판은 준비 완료, 색인판 계보에 표시.
        cloud = index_fixture.FakeCloudStore()
        cloud.connection.understanding_payload = copy.deepcopy(understanding)
        cloud.connection.extraction_payload = {**copy.deepcopy(extraction), 'understanding_result_id': 'understanding-cp3'}  # 색인 대역의 판정 ID
        PostgresDocumentIndex(cloud).index_result(self.context, result)
        self.assertNotIn('evidence_spans', cloud.connection.inserts)
        self.assertIn('index_versions', cloud.connection.inserts)
        self.assertEqual(cloud.connection.source_state, 'ready')
        self.assertEqual(cloud.connection.index_payload['chunks'], [])
        self.assertEqual(cloud.connection.index_payload['lineage']['aggregation_only'], 'true')
        self.assertEqual(PostgresDocumentIndex(cloud).search(self.context, source_id='source-cp3', source_version_id='source-version-cp3', query='매출 합계'), ())

    def test_aggregation_only_completion_rejects_forged_flag_for_small_original(self):
        content = original()
        store, storage = processing_fixture(content)
        repository = PostgresDocumentProcessingRepository(store, storage)
        from daon2_user_api.xlsx_document_understanding import aggregation_only_result
        document = repository.load_source_document(self.context, 'source-cp3', processing_run_id='run-cp3')
        forged = aggregation_only_result(document, self.context)
        with self.assertRaises(DocumentUnderstandingError):
            repository.complete(self.context, 'run-cp3', forged)
        self.assertEqual(inserted(store, 'understanding_results'), [])
        self.assertEqual(store.connection.states['ProcessingRun'], 'vision_llm_understanding')

    def test_corrupted_xlsx_still_fails(self):
        def macro(entries):
            entries['[Content_Types].xml'] = entries['[Content_Types].xml'].replace(b'sheet.main+xml', b'sheet.macroEnabled.main+xml')
        def external(entries):
            entries['xl/_rels/workbook.xml.rels'] = entries['xl/_rels/workbook.xml.rels'].replace(
                b'</Relationships>', b'<Relationship Id="rX" Type="x" Target="https://example.invalid/a" TargetMode="External"/></Relationships>')
        for label, content in (('broken-zip', b'PK\x03\x04broken'), ('truncated', large_xlsx()[:-200]),
                               ('large-with-macro', large_xlsx(extra=macro)), ('large-with-external-link', large_xlsx(extra=external))):
            with self.subTest(label=label):
                store, storage = processing_fixture(content)
                queue = FakeQueue(job())
                service = DocumentProcessingService(PostgresDocumentProcessingRepository(store, storage), Resolver(),
                                                    AdapterFactory(Adapter()), xlsx_adapter=ExplodingXlsxAdapter())
                worker = DocumentProcessingWorker('worker-cp3', queue, service, FakeIndex(queue.events), clock=lambda: NOW)
                self.assertTrue(worker.run_once())
                self.assertEqual(queue.events[-1], ('dead_letter', 'SOURCE_OBJECT_NOT_READY'))
                self.assertEqual(store.connection.states['ProcessingRun'], 'failed')
                self.assertEqual(inserted(store, 'understanding_results'), [])

    def test_small_xlsx_unchanged(self):
        content = original()
        store, storage = processing_fixture(content)
        resolver = Resolver(); queue = FakeQueue(job())
        from daon2_user_api.xlsx_document_understanding import OllamaXlsxDocumentAdapter
        service = DocumentProcessingService(PostgresDocumentProcessingRepository(store, storage), resolver,
                                            AdapterFactory(Adapter()), xlsx_adapter=OllamaXlsxDocumentAdapter(Transport()))
        worker = DocumentProcessingWorker('worker-cp3', queue, service, FakeIndex(queue.events), clock=lambda: NOW)
        self.assertTrue(worker.run_once())
        self.assertEqual(resolver.calls, ['text_generation'])
        self.assertEqual(sum(event[0] == 'index' for event in queue.events), 1)
        (understanding,) = inserted(store, 'understanding_results')
        self.assertNotIn('aggregation_only', understanding['lineage'])
        self.assertEqual(len(understanding['parser_validation']['cell_evidence']), 3)

    def test_question_with_only_aggregation_sources_returns_code(self):
        searched = []

        class Repository(FakeRepository):
            def load_ready_source(self, context, source_id, source_version_id):
                return ReadyQuestionSource(source_id, source_version_id, f'{source_id}.xlsx',
                                           aggregation_only=source_id.startswith('agg'))

        class Index(QuestionIndex):
            def search(self, context, **kwargs):
                searched.append(kwargs['source_version_id'])
                return super().search(context, **kwargs)

        chunk = IndexedEvidenceChunk('chunk-1', 'pdf-1', 'pdf-v1', 1, '매출 근거', 'span-1', 0.9)
        transport = FakeTransport()
        service = QuestionAnsweringService(FakeProviderSettings(), Repository(), Index({'pdf-v1': (chunk,)}),
                                           FakeCredential(), transport, FakeEgress())
        context = QuestionContext('tenant-cp3', 'workspace-cp3', 'actor-cp3', 'trace-cp3', 'policy-v1')
        only = (QuestionInputSource('raw_source', 'agg-1', 'agg-1', 'agg-v1'), QuestionInputSource('raw_source', 'agg-2', 'agg-2', 'agg-v2'))
        with self.assertRaises(QuestionAnsweringError) as raised:
            service.ask(context, source_id='agg-1', source_version_id='agg-v1', question='매출 합계를 알려줘',
                        run_id='run-agg', context_sources=only)
        self.assertEqual((raised.exception.code, raised.exception.status), ('SOURCE_AGGREGATION_ONLY', 409))
        with self.assertRaises(QuestionAnsweringError) as prepared:
            service.prepare_authorization(context, source_id='agg-1', source_version_id='agg-v1',
                                          question='매출 합계를 알려줘', context_sources=only)
        self.assertEqual(prepared.exception.code, 'SOURCE_AGGREGATION_ONLY')
        self.assertEqual((searched, transport.calls), ([], 0))
        # 일반 소스가 섞이면 집계 전용 소스만 근거에서 빠진다.
        mixed = (QuestionInputSource('raw_source', 'agg-1', 'agg-1', 'agg-v1'), QuestionInputSource('raw_source', 'pdf-1', 'pdf-1', 'pdf-v1'))
        service.prepare_authorization(context, source_id='agg-1', source_version_id='agg-v1',
                                      question='매출 합계를 알려줘', context_sources=mixed)
        self.assertEqual(searched, ['pdf-v1'])
        # 화면에 코드가 그대로 보이도록 공개 코드 목록과 한국어 문구가 있다.
        root = Path(__file__).resolve().parents[3]
        runtime = (root / 'services/api/src/daon2_user_api/runtime.py').read_text(encoding='utf-8')
        handler = runtime.split('async def question_answering_error', 1)[1].split('async def question_repository_error', 1)[0]
        self.assertIn('"SOURCE_AGGREGATION_ONLY"', handler)
        shell = (root / 'packages/ui/src/product-workspace-shell.jsx').read_text(encoding='utf-8')
        self.assertTrue('"SOURCE_AGGREGATION_ONLY"' in shell, 'UI 질문 오류 문구 없음')
        self.assertTrue(AGG_MESSAGE in shell, 'UI 한국어 문구 없음')

    def test_question_repository_reads_aggregation_flag_from_index_lineage(self):
        from dataclasses import replace
        from test_question_answering_postgres import FakeCloudStore as QuestionCloud
        from daon2_user_api.question_answering_postgres import PostgresQuestionAnsweringRepository
        cloud = QuestionCloud()
        connection = cloud.connection
        row = list(connection.ready_row); row[3] = 'sales.xlsx'; row[8] = XLSX
        connection.ready_row = tuple(row)
        repository = PostgresQuestionAnsweringRepository(cloud, FakeObjectStorage())
        context = QuestionContext('tenant-cp3', 'workspace-cp3', 'actor-cp3', 'trace-cp3', 'policy-v1')
        self.assertFalse(repository.load_ready_source(context, 'source-cp3', 'source-version-cp3').aggregation_only)
        sql = connection.queries[-1]
        self.assertIn("canonical_json->'lineage'->>'aggregation_only'='true'", sql.split(' FROM sources s JOIN', 1)[0])
        original_execute = connection.execute

        def flagged(sql, params=()):
            cursor = original_execute(sql, params)
            if sql.startswith('SELECT s.record_id,sv.record_id,s.state') and cursor.row is not None:
                cursor.row = (*cursor.row, True)
            return cursor
        connection.execute = flagged
        self.assertTrue(repository.load_ready_source(replace(context), 'source-cp3', 'source-version-cp3').aggregation_only)

    def test_source_list_exposes_flag(self):
        from daon2_user_api.runtime import _dataclass_json
        from daon2_user_api.studio_report import StudioReportContext
        from daon2_user_api.studio_report_postgres import PostgresStudioReportRepository
        statements = []

        class Cursor:
            def __init__(self, row=None, rows=()):
                self.row, self.rows = row, list(rows)
            def fetchone(self): return self.row
            def fetchall(self): return self.rows

        class Connection:
            def execute(self, sql, params=()):
                statements.append(sql)
                if sql.startswith('SELECT canonical_json FROM source_versions'):
                    return Cursor(({},))
                return Cursor(rows=[
                    ('agg-1', 'agg-v1', 'sales.xlsx', 'ready', 'completed', 'completed', False, None, True),
                    ('pdf-1', 'pdf-v1', 'a.pdf', 'ready', 'completed', 'completed', False, None, False),
                ])

        class Cloud:
            @contextmanager
            def _transaction(self, scope):
                yield Connection()

        context = StudioReportContext('tenant-cp3', 'workspace-cp3', 'actor-cp3', 'trace-cp3', 'policy-v1', 'notebook-cp3')
        agg, pdf = PostgresStudioReportRepository(Cloud()).list_sources(context)
        self.assertIs(agg.aggregation_only, True)
        self.assertEqual(_dataclass_json(agg)['aggregation_only'], True)
        self.assertNotIn('aggregation_only', _dataclass_json(pdf))
        self.assertEqual(len(_dataclass_json(pdf)), 6)
        self.assertIn("canonical_json->'lineage'->>'aggregation_only'='true'", statements[0])

    def test_studio_text_reader_skips_aggregation_only(self):
        class Cursor:
            def __init__(self, row=None, rows=()):
                self.row, self.rows = row, list(rows)
            def fetchone(self): return self.row
            def fetchall(self): return self.rows

        empty_parser = {'text': '', 'markdown': '', 'html': '', 'pages': [], 'page_texts': [], 'role': 'validation_only',
                        'regions': [], 'cell_evidence': []}
        rows = {'agg-v1': ('agg-1', 'sales.xlsx', empty_parser),
                'pdf-v1': ('pdf-1', 'a.pdf', {'text': '본문 글', 'markdown': '', 'page_texts': []})}

        class Connection:
            def execute(self, sql, params=()):
                if sql.startswith('SELECT sv.source_id'):
                    return Cursor(rows[params[2]])
                return Cursor(rows=[])  # 집계 전용 판에는 근거 구간이 없다.

        class Cloud:
            @contextmanager
            def _transaction(self, scope):
                yield Connection()

        context = StudioContext('tenant-cp3', 'workspace-cp3', 'actor-cp3', 'trace-cp3', 'policy-v1', 'notebook-cp3')
        reader = StudioSourceReader(Cloud())
        texts = reader.read(context, ['agg-v1', 'pdf-v1'])
        self.assertEqual({item.source_version_id: len(item.sections) for item in texts}, {'agg-v1': 0, 'pdf-v1': 1})
        self.assertNotIn('sales', ' '.join(section.text for item in texts for section in item.sections))
        with self.assertRaises(StudioError) as raised:
            reader.read(context, ['agg-v1'])
        self.assertEqual(raised.exception.code, 'STUDIO_NO_READY_SOURCE')


if __name__ == '__main__':
    unittest.main()
