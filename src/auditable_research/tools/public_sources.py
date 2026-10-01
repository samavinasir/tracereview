import asyncio
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from defusedxml import ElementTree as ET

from ..config import settings
from ..models import SearchQuery, SourceRecord, SourceSection
from .base import ResearchTool


def _record(provider: str, uid: str, title: str, url: str, abstract: str = "", authors: list[str] | None = None, year: int | None = None, raw: dict[str, Any] | None = None) -> SourceRecord:
    # Keep only compact bibliographic metadata. Provider payloads (especially OpenAlex)
    # can contain enormous inverted abstracts and are not needed for evidence citations.
    metadata_keys = {
        "pubmed": {"uid", "pubdate", "pubtype"},
        "europe_pmc": {"id", "pmid", "pmcid", "doi", "firstPublicationDate", "journalTitle", "isOpenAccess", "source"},
        "crossref": {"DOI", "type", "publisher", "volume", "issue", "page"},
        "openalex": {"id", "doi", "type", "publication_year"},
        "semantic_scholar": {"paperId", "externalIds", "openAccessPdf"},
        "uniprot": {"primaryAccession", "entryType"},
    }.get(provider, set())
    compact_raw = {key: value for key, value in (raw or {}).items() if key in metadata_keys}
    return SourceRecord(source_id=f"{provider}:{uid}", provider=provider, title=title or "Untitled record", authors=authors or [], publication_year=year, url=url, abstract=abstract[:12000], raw_metadata=compact_raw)


class HttpResearchTool(ResearchTool):
    async def get(self, url: str, params: dict | None = None, headers: dict[str, str] | None = None) -> dict:
        request_headers = {"User-Agent": "TraceReview/0.2 (open-source research tool)", **(headers or {})}
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=request_headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_text(self, url: str, params: dict | None = None, max_bytes: int = 5_000_000) -> str:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers={"User-Agent": "TraceReview/0.2 (open-source research tool)"}) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            if len(response.content) > max_bytes:
                raise ValueError("External full text exceeded the configured response size limit")
            return response.text


class PubMedTool(HttpResearchTool):
    name = "pubmed"

    def __init__(self) -> None:
        # E-utilities limits are per source IP/account, so pace every PubMed
        # request (including esummary/efetch) through this shared tool instance.
        self._request_interval = 0.34 if not settings.ncbi_api_key else 0.11
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def _wait_for_ncbi_slot(self) -> None:
        async with self._request_lock:
            now = time.monotonic()
            scheduled = max(now, self._next_request_at)
            self._next_request_at = scheduled + self._request_interval
        delay = scheduled - now
        if delay > 0:
            await asyncio.sleep(delay)

    def _ncbi_params(self, params: dict[str, Any]) -> dict[str, Any]:
        result = {**params, "tool": "TraceReview"}
        if settings.contact_email:
            result["email"] = settings.contact_email
        if settings.ncbi_api_key:
            result["api_key"] = settings.ncbi_api_key
        return result

    async def _get_ncbi(self, url: str, params: dict[str, Any]) -> dict:
        await self._wait_for_ncbi_slot()
        return await self.get(url, self._ncbi_params(params))

    async def _get_ncbi_text(self, url: str, params: dict[str, Any]) -> str:
        await self._wait_for_ncbi_slot()
        return await self.get_text(url, params=self._ncbi_params(params))

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        root = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        found = await self._get_ncbi(f"{root}/esearch.fcgi", {"db": "pubmed", "term": query.query, "retmax": limit, "retmode": "json"})
        ids = found.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        details = await self._get_ncbi(f"{root}/esummary.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
        abstract_xml = await self._get_ncbi_text(f"{root}/efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "xml"})
        abstracts: dict[str, str] = {}
        try:
            root_element = ET.fromstring(abstract_xml)
            for citation in root_element.iter():
                if citation.tag.rsplit("}", 1)[-1] != "PubmedArticle":
                    continue
                pmid = next((element.text for element in citation.iter() if element.tag.rsplit("}", 1)[-1] == "PMID" and element.text), None)
                if not pmid:
                    continue
                parts = []
                for element in citation.iter():
                    if element.tag.rsplit("}", 1)[-1] == "AbstractText":
                        text = " ".join("".join(element.itertext()).split())
                        if text:
                            parts.append(text)
                abstracts[pmid] = " ".join(parts)
        except ET.ParseError:
            abstracts = {}
        result = details.get("result", {})
        records = []
        for uid in ids:
            item = result.get(uid, {})
            authors = [a.get("name", "") for a in item.get("authors", [])]
            date = item.get("pubdate", "")[:4]
            records.append(_record(self.name, uid, item.get("title", ""), f"https://pubmed.ncbi.nlm.nih.gov/{uid}/", abstract=abstracts.get(uid, ""), authors=authors, year=int(date) if date.isdigit() else None, raw=item))
        return records


class EuropePMCTool(HttpResearchTool):
    name = "europe_pmc"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        payload = await self.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", {"query": query.query, "format": "json", "pageSize": limit, "resultType": "core"})
        records = []
        for item in payload.get("resultList", {}).get("result", []):
            uid = str(item.get("pmid") or item.get("id") or uuid4())
            authors = [a.get("fullName", "") for a in item.get("authorList", {}).get("author", [])]
            year = item.get("firstPublicationDate", "")[:4]
            records.append(_record(self.name, uid, item.get("title", ""), item.get("doi") and f"https://doi.org/{item['doi']}" or f"https://europepmc.org/article/MED/{uid}", item.get("abstractText", ""), authors, int(year) if year.isdigit() else None, item))
        return records

    async def fetch_full_text(self, source: SourceRecord) -> SourceRecord:
        pmcid = source.raw_metadata.get("pmcid")
        if not pmcid or source.raw_metadata.get("isOpenAccess") != "Y":
            return source
        identifier = str(pmcid).removeprefix("PMC")
        xml = await self.get_text(f"https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{identifier}/fullTextXML")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return source

        sections: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def visit(element: Any, active_part: str | None = None, section_title: str = "") -> None:
            tag = element.tag.rsplit("}", 1)[-1].casefold()
            part, title = active_part, section_title
            if tag == "sec":
                own_title = next((" ".join("".join(child.itertext()).split()) for child in element if child.tag.rsplit("}", 1)[-1].casefold() == "title"), "")
                heading = own_title.casefold()
                if any(word in heading for word in ("method", "material", "experiment", "strain", "construct")):
                    part = "methods"
                elif any(word in heading for word in ("result", "phenotype", "susceptibility", "antimicrobial activity")):
                    part = "results"
                title = own_title or title
            if tag == "p" and part in {"methods", "results"}:
                text = " ".join("".join(element.itertext()).split())
                key = (part, text)
                if text and key not in seen and len(sections) < 8:
                    sections.append({"source_part": part, "title": title or part.title(), "text": text[:1200]})
                    seen.add(key)
                return
            for child in element:
                visit(child, part, title)

        visit(root)
        source.full_text_sections = [SourceSection.model_validate(item) for item in sections[:8]]
        return source


class CrossrefTool(HttpResearchTool):
    name = "crossref"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        payload = await self.get("https://api.crossref.org/works", {"query.bibliographic": query.query, "rows": limit})
        records = []
        for item in payload.get("message", {}).get("items", []):
            doi = item.get("DOI", "")
            date = (item.get("published", {}).get("date-parts") or [[None]])[0][0]
            authors = [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in item.get("author", [])]
            records.append(_record(self.name, doi or uuid4().hex, (item.get("title") or [""])[0], f"https://doi.org/{doi}" if doi else item.get("URL", ""), item.get("abstract", ""), authors, int(date) if date else None, item))
        return records


class OpenAlexTool(HttpResearchTool):
    name = "openalex"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        payload = await self.get("https://api.openalex.org/works", {"search": query.query, "per-page": limit})
        records = []
        for item in payload.get("results", []):
            authors = [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])]
            abstract_index = item.get("abstract_inverted_index") or {}
            abstract_words: list[str] = []
            if abstract_index:
                positions = {position: word for word, indexes in abstract_index.items() for position in indexes}
                abstract_words = [positions[position] for position in sorted(positions)]
            abstract = " ".join(abstract_words)
            records.append(_record(self.name, item.get("id", "").rsplit("/", 1)[-1], item.get("title", ""), item.get("doi") or item.get("id", ""), abstract=abstract, authors=authors, year=item.get("publication_year"), raw=item))
        return records


class UniProtTool(HttpResearchTool):
    name = "uniprot"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        payload = await self.get("https://rest.uniprot.org/uniprotkb/search", {"query": query.query, "format": "json", "size": limit})
        records = []
        for item in payload.get("results", []):
            accession = item.get("primaryAccession", "")
            protein = item.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", "")
            organism = item.get("organism", {}).get("scientificName", "")
            records.append(_record(self.name, accession, f"{protein} ({organism})", f"https://www.uniprot.org/uniprotkb/{quote(accession)}", raw=item))
        return records


class SemanticScholarTool(HttpResearchTool):
    name = "semantic_scholar"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else None
        payload = await self.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query.query, "limit": min(limit, 100), "fields": "paperId,title,year,abstract,authors,externalIds,openAccessPdf"},
            headers=headers,
        )
        records = []
        for item in payload.get("data", []):
            paper_id = item.get("paperId")
            if not paper_id:
                continue
            external_ids = item.get("externalIds") or {}
            pdf = item.get("openAccessPdf") or {}
            url = f"https://www.semanticscholar.org/paper/{paper_id}"
            records.append(_record(
                self.name,
                paper_id,
                item.get("title", ""),
                url,
                abstract=item.get("abstract") or "",
                authors=[author.get("name", "") for author in item.get("authors", []) if author.get("name")],
                year=item.get("year"),
                raw={"paperId": paper_id, "externalIds": external_ids, "openAccessPdf": pdf},
            ))
        return records
