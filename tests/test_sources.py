from unittest.mock import AsyncMock

import pytest

from auditable_research.models import SearchQuery, SourceRecord
from auditable_research.tools.public_sources import (
    CrossrefTool,
    EuropePMCTool,
    OpenAlexTool,
    PubMedTool,
    SemanticScholarTool,
    UniProtTool,
)


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery(query_id="Q1", subquestion="Mechanisms", query="resistance mechanisms", source_names=["pubmed"])


@pytest.mark.asyncio
async def test_pubmed_client_parses_records(query: SearchQuery, monkeypatch: pytest.MonkeyPatch) -> None:
    from auditable_research.config import settings

    monkeypatch.setattr(settings, "ncbi_api_key", "test-ncbi-key")
    monkeypatch.setattr(settings, "contact_email", "test@example.org")
    tool = PubMedTool()
    tool._request_interval = 0
    tool.get = AsyncMock(side_effect=[{"esearchresult": {"idlist": ["123"]}}, {"result": {"123": {"title": "Study", "pubdate": "2024 Jan", "authors": [{"name": "A. Author"}]}}}])
    tool.get_text = AsyncMock(return_value="<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><Abstract><AbstractText>Controlled assay result</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>")

    records = await tool.search(query, 5)

    assert records[0].source_id == "pubmed:123"
    assert records[0].publication_year == 2024
    assert records[0].url == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert records[0].abstract == "Controlled assay result"
    assert tool.get.await_count == 2
    assert tool.get.await_args_list[0].args[1]["api_key"] == "test-ncbi-key"
    assert tool.get.await_args_list[0].args[1]["email"] == "test@example.org"
    assert tool.get.await_args_list[0].args[1]["tool"] == "TraceReview"
    assert "api_key" in tool.get_text.await_args.kwargs["params"]
    tool.get_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_europe_pmc_client_parses_abstract(query: SearchQuery) -> None:
    tool = EuropePMCTool()
    tool.get = AsyncMock(return_value={"resultList": {"result": [{"pmid": "456", "title": "Study", "firstPublicationDate": "2023-04-01", "abstractText": "Observed phenotype", "authorList": {"author": [{"fullName": "B Author"}]}}]}})

    records = await tool.search(query, 5)

    assert records[0].source_id == "europe_pmc:456"
    assert records[0].abstract == "Observed phenotype"
    assert records[0].authors == ["B Author"]


@pytest.mark.asyncio
async def test_crossref_client_parses_doi_and_year(query: SearchQuery) -> None:
    tool = CrossrefTool()
    tool.get = AsyncMock(return_value={"message": {"items": [{"DOI": "10.1000/example", "title": ["Study"], "published": {"date-parts": [[2022]]}, "author": [{"given": "C", "family": "Author"}], "abstract": "An observation"}]}})

    records = await tool.search(query, 5)

    assert records[0].source_id == "crossref:10.1000/example"
    assert records[0].url == "https://doi.org/10.1000/example"
    assert records[0].publication_year == 2022


@pytest.mark.asyncio
async def test_openalex_client_reconstructs_inverted_abstract(query: SearchQuery) -> None:
    tool = OpenAlexTool()
    tool.get = AsyncMock(return_value={"results": [{"id": "https://openalex.org/W1", "title": "Study", "publication_year": 2021, "abstract_inverted_index": {"resistance": [1], "Observed": [0]}}]})

    records = await tool.search(query, 5)

    assert records[0].source_id == "openalex:W1"
    assert records[0].abstract == "Observed resistance"


@pytest.mark.asyncio
async def test_uniprot_client_parses_protein_record(query: SearchQuery) -> None:
    tool = UniProtTool()
    tool.get = AsyncMock(return_value={"results": [{"primaryAccession": "P12345", "proteinDescription": {"recommendedName": {"fullName": {"value": "Example protein"}}}, "organism": {"scientificName": "Klebsiella pneumoniae"}}]})

    records = await tool.search(query, 5)

    assert records[0].source_id == "uniprot:P12345"
    assert "Example protein" in records[0].title
    assert records[0].url.startswith("https://")


@pytest.mark.asyncio
async def test_europe_pmc_fetches_only_open_access_methods_and_results(query: SearchQuery) -> None:
    tool = EuropePMCTool()
    tool.get_text = AsyncMock(return_value="""<article><body><sec><title>Methods</title><p>Cells were tested by MIC assay.</p></sec><sec><title>Results</title><p>OmpK36 disruption raised the MIC.</p></sec><sec><title>Discussion</title><p>Context only.</p></sec></body></article>""")
    source = SourceRecord(source_id="europe_pmc:PMC123", provider="europe_pmc", title="Study", url="https://example.org", raw_metadata={"pmcid": "PMC123", "isOpenAccess": "Y"})

    result = await tool.fetch_full_text(source)

    assert [section.source_part for section in result.full_text_sections] == ["methods", "results"]
    assert "MIC assay" in result.full_text_sections[0].text
    assert "Context only" not in " ".join(section.text for section in result.full_text_sections)
    tool.get_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_semantic_scholar_client_parses_paper(query: SearchQuery, monkeypatch: pytest.MonkeyPatch) -> None:
    from auditable_research.config import settings

    monkeypatch.setattr(settings, "semantic_scholar_api_key", "test-semantic-scholar-key")
    tool = SemanticScholarTool()
    tool.get = AsyncMock(return_value={"data": [{"paperId": "abc", "title": "Porin study", "year": 2024, "abstract": "Observed MIC change", "authors": [{"name": "A Author"}], "externalIds": {"DOI": "10.1000/example"}, "openAccessPdf": {"url": "https://example.org/paper.pdf"}}]})

    records = await tool.search(query, 5)

    assert records[0].source_id == "semantic_scholar:abc"
    assert records[0].abstract == "Observed MIC change"
    assert records[0].raw_metadata["externalIds"]["DOI"] == "10.1000/example"
    assert tool.get.await_args.kwargs["headers"] == {"x-api-key": "test-semantic-scholar-key"}
