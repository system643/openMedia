"""Veille de recherche : lecture des archives ouvertes et règle d'indépendance entre papiers."""

from openmedia.agents.material import independence_key
from openmedia.collect import research
from openmedia.models import Article, Source

ARXIV = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry>
  <id>http://arxiv.org/abs/2610.01234v1</id>
  <published>2026-10-15T17:00:00Z</published>
  <title>Self-Verifying   Agents for
  Multi-Step Reasoning</title>
  <summary>We propose a method that lets language model agents verify each step. It improves accuracy by 12 points on GSM-Hard.</summary>
  <author><name>Ada Martin</name></author><author><name>Li Wei</name></author>
  <arxiv:primary_category term="cs.AI"/>
</entry>
</feed>"""

PUBMED = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>40123456</PMID><Article><Journal><Title>Nature Medicine</Title><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month><Day>14</Day></PubDate></JournalIssue></Journal>
<ArticleTitle>CRISPR base editing in sickle cell disease</ArticleTitle><Abstract><AbstractText Label="RESULTS">In 45 patients, editing was durable.</AbstractText></Abstract>
<AuthorList><Author><LastName>Dupont</LastName><ForeName>Marie</ForeName></Author></AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""


def test_arxiv_entries_keep_title_abstract_and_category():
    [p] = research.parse_arxiv(ARXIV)
    assert p.title == "Self-Verifying Agents for Multi-Step Reasoning"
    assert p.url == "https://arxiv.org/abs/2610.01234v1" and p.source_name == "arXiv cs.AI"
    assert p.extra["preprint"] and p.extra["authors"] == ["Ada Martin", "Li Wei"] and "12 points" in p.snippet


def test_openalex_rebuilds_the_abstract():
    payload = {"results": [{"title": "Sea level rise", "abstract_inverted_index": {"Sea": [0], "levels": [1], "rise": [2], "faster.": [3]}, "publication_date": "2026-10-10", "doi": "https://doi.org/10.1/x", "type": "article", "primary_location": {"landing_page_url": "https://www.nature.com/articles/x", "source": {"display_name": "Nature"}, "version": "publishedVersion"}, "authorships": [{"author": {"display_name": "A. B."}}]}]}
    [p] = research.parse_openalex(payload)
    assert p.snippet == "Sea levels rise faster." and p.source_name == "Nature" and not p.extra["preprint"]


def test_pubmed_parsing():
    [p] = research.parse_pubmed(PUBMED)
    assert p.url.endswith("/40123456/") and p.source_name == "Nature Medicine"
    assert p.published_at.month == 10 and "45 patients" in p.snippet and p.extra["authors"] == ["Marie Dupont"]


def test_hal_and_biorxiv_parsing():
    [h] = research.parse_hal({"response": {"docs": [{"title_s": ["Titre"], "abstract_s": ["Résumé"], "uri_s": "https://hal.science/hal-1", "producedDate_tdate": "2026-10-12T00:00:00Z", "docType_s": "ART"}, {"title_s": ["Sans résumé"], "uri_s": "u"}]}})
    assert h.url == "https://hal.science/hal-1"
    [b] = research.parse_biorxiv({"collection": [{"doi": "10.1101/x", "title": "CRISPR screen", "abstract": "We used CRISPR.", "date": "2026-10-12", "authors": "A; B"}, {"doi": "10.1101/y", "title": "Plants", "abstract": "Leaves", "date": "2026-10-12"}]}, "biorxiv", ["crispr"])
    assert b.url.endswith("10.1101/x") and b.extra["preprint"]


def test_two_papers_are_two_sources_but_two_press_reprints_are_one():
    arxiv = Source(domain="arxiv.org", name="arXiv", owner="Cornell")
    p1 = Article(id=1, url="a", title="t", domain="arxiv.org", kind="recherche")
    p2 = Article(id=2, url="b", title="t", domain="arxiv.org", kind="recherche")
    assert independence_key(p1, arxiv) != independence_key(p2, arxiv)
    press = Source(domain="lemonde.fr", name="Le Monde", owner="Groupe Le Monde")
    a1 = Article(id=3, url="c", title="t", domain="lemonde.fr", wire="AFP")
    a2 = Article(id=4, url="d", title="t", domain="lefigaro.fr", wire="AFP")
    assert independence_key(a1, press) == independence_key(a2, press)


def test_field_options():
    ids = {f["id"] for f in research.field_options()}
    assert {"ia", "informatique", "biologie", "medecine"} <= ids
