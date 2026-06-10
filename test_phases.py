import sys
sys.path.insert(0, '.')
errors = []

# Phase 0
try:
    from finagent.output.output_scrubber import scrub_output, scrub_and_comply, ScrubResult
    print('OK: output_scrubber')
except Exception as e:
    errors.append('output_scrubber: ' + str(e))

try:
    from finagent.runtime_provider import resolve_openai_config
    print('OK: runtime_provider')
except Exception as e:
    errors.append('runtime_provider: ' + str(e))

# Phase 1
try:
    from finagent.agents.blueprint import BlueprintSpec, generate_blueprint
    spec = generate_blueprint('test query', 'Test Corp')
    assert spec.query == 'test query'
    print('OK: blueprint (functional test passed)')
except Exception as e:
    errors.append('blueprint: ' + str(e))

try:
    from finagent.agents.grader import grade_research, ResearchQualityScore
    result = grade_research('This is a test synthesis output with some content.')
    assert isinstance(result.total_score, int)
    print('OK: grader (score=%d/100, passed=%s)' % (result.total_score, result.passed))
except Exception as e:
    errors.append('grader: ' + str(e))

# Phase 2
try:
    from finagent.ikg.schema import CompanyNode, PersonNode, DirectorOfEdge
    node = CompanyNode(cin='L17110MH1973PLC019786', name='Reliance Industries')
    assert node.vertex_id == 'company:L17110MH1973PLC019786'
    print('OK: ikg.schema')
except Exception as e:
    errors.append('ikg.schema: ' + str(e))

try:
    from finagent.ikg.graph_client import IKGClient, InMemoryGraphBackend
    client = IKGClient(backend=InMemoryGraphBackend())
    print('OK: graph_client (in-memory backend)')
except Exception as e:
    errors.append('graph_client: ' + str(e))

try:
    from finagent.ikg.scrapers.mca_companies import stream_mca_records
    print('OK: mca_companies')
except Exception as e:
    errors.append('mca_companies: ' + str(e))

try:
    from finagent.ikg.pipeline.orchestrator import get_pipeline_health
    print('OK: pipeline.orchestrator')
except Exception as e:
    errors.append('pipeline.orchestrator: ' + str(e))

# Phase 3
try:
    from finagent.learning.strategy_loader import format_strategies_for_context
    result = format_strategies_for_context([])
    assert result == ''
    print('OK: strategy_loader')
except Exception as e:
    errors.append('strategy_loader: ' + str(e))

# Phase 4
try:
    from finagent.dreaming.consolidator import extract_verified_claims
    claims = extract_verified_claims(
        'Revenue of INR 2,45,000 crore in FY25 [Source: Annual Report]',
        entity_name='Test Co'
    )
    print('OK: consolidator (extracted %d claims)' % len(claims))
except Exception as e:
    errors.append('consolidator: ' + str(e))

try:
    from finagent.dreaming.preloader import format_card_for_context
    print('OK: preloader')
except Exception as e:
    errors.append('preloader: ' + str(e))

# Phase 5
try:
    from finagent.ingestion.azure_doc_intel import is_azure_di_configured, DocumentIntelligenceResult
    print('OK: azure_doc_intel (configured=%s)' % is_azure_di_configured())
except Exception as e:
    errors.append('azure_doc_intel: ' + str(e))

try:
    from finagent.graphrag.indexer import index_document, DocumentChunk
    chunks = index_document(
        'This is a test document with some financial content about revenue growth.',
        source_file='test.txt'
    )
    print('OK: graphrag.indexer (created %d chunks)' % len(chunks))
except Exception as e:
    errors.append('graphrag.indexer: ' + str(e))

try:
    from finagent.ikg.scrapers.sebi_enforcement import extract_entities_from_order_text
    entities = extract_entities_from_order_text(
        'SEBI penalized XYZ Limited CIN L12345MH2020PLC123456 DIN: 12345678 penalty of Rs. 5 crore'
    )
    cins = entities.get('cins', [])
    dins = entities.get('dins', [])
    penalties = entities.get('penalties', [])
    assert cins == ['L12345MH2020PLC123456']
    assert dins == ['12345678']
    assert penalties == [50000000.0]
    print('OK: sebi_enforcement NER (cins=%s dins=%s penalties=%s)' % (cins, dins, penalties))
except Exception as e:
    errors.append('sebi_enforcement: ' + str(e))

# Test MCA CSV streaming (dry run - just check first 3 records)
try:
    from finagent.ikg.scrapers.mca_companies import stream_mca_records
    count = 0
    for rec in stream_mca_records(listed_only=True):
        count += 1
        if count >= 3:
            break
    assert count == 3
    print('OK: mca_companies stream (read %d listed records)' % count)
except Exception as e:
    errors.append('mca_companies_stream: ' + str(e))

# Test output scrubber functional
try:
    from finagent.output.output_scrubber import scrub_output
    test_text = 'The stock verdict is "STRONG BUY" because it is undervalued.'
    result = scrub_output(test_text)
    assert 'STRONG BUY' not in result.text
    assert 'undervalued' not in result.text.lower() or 'below_model' in result.text
    print('OK: output_scrubber functional (scrubbed %d patterns)' % len(result.actions))
except Exception as e:
    errors.append('output_scrubber_functional: ' + str(e))

print()
if errors:
    print('ERRORS (%d):' % len(errors))
    for e in errors:
        print('  - ' + e)
else:
    print('ALL IMPORTS AND FUNCTIONAL TESTS PASSED')
