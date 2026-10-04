"""The three Agent read routes: company list, company-scoped item and the direct item.

All of them need ``read:agent`` and a person or API key (never a run token). The two with a
company in the URL take ``PathCompanyId``: a company that is not the caller's, existing or not,
is the same 403 in every UUID spelling and no Agent query runs for it. The direct route takes
the caller's company from the principal, so a foreign id is the same 404 as a missing one. The
list is paged in SQL with a bounded limit.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, get_args, get_origin

import httpx
import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from nexus.api.deps import get_current_company_id, get_scoped_company_id
from nexus.api.routes import agents as agent_routes
from nexus.models.agent import Agent
from tests.test_agent_route_security import route_world  # noqa: F401 -- fixture
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_goal_route_security import _sql
from tests.test_task_route_security import FORMS, _flatten
from tests.test_work_service import co  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

LIST = "/api/v1/companies/{company}/agents"
ITEM = "/api/v1/companies/{company}/agents/{agent}"
DIRECT = "/api/v1/agents/{agent}"


def _urls(company, agent):
    return (LIST.format(company=company), ITEM.format(company=company, agent=agent))


def _all_urls(co):
    return (*_urls(co["acme"], co["acme_eve"]), DIRECT.format(agent=co["acme_eve"]))


class TestPathCompany:
    @pytest.mark.parametrize("form", FORMS)
    async def test_own_company_works_in_every_uuid_form(self, form, co, route_world):
        company = FORMS[form](co["acme"])
        listed = await route_world("GET", LIST.format(company=company))
        item = await route_world("GET", ITEM.format(company=company, agent=co["acme_eve"]))
        assert (listed.status_code, item.status_code) == (200, 200)
        ids = {a["id"] for a in listed.json()}
        assert str(co["acme_eve"]) in ids and str(co["other_eve"]) not in ids
        assert {a["company_id"] for a in listed.json()} == {str(co["acme"])}
        assert item.json()["id"] == str(co["acme_eve"])

    @pytest.mark.parametrize("form", FORMS)
    async def test_foreign_and_nonexistent_company_get_the_same_refusal(
        self, form, co, route_world
    ):
        spell = FORMS[form]
        for agent in (co["acme_eve"], co["other_eve"], uuid.uuid4()):
            for url_of in (
                lambda c: LIST.format(company=spell(c)),
                lambda c: ITEM.format(company=spell(c), agent=agent),
            ):
                answers = []
                for target in (co["other"], uuid.uuid4()):
                    with _sql(co) as seen:
                        res = await route_world("GET", url_of(target), "api_key")
                    assert seen == [], (url_of(target), seen)
                    answers.append((res.status_code, res.json()))
                assert answers[0] == answers[1] and answers[0][0] == 403, answers

    async def test_a_foreign_company_never_falls_back_to_the_callers_company(self, co, route_world):
        # The caller's own agent under a foreign company in the URL must not be served.
        res = await route_world("GET", ITEM.format(company=co["other"], agent=co["acme_eve"]))
        assert res.status_code == 403 and str(co["acme_eve"]) not in res.text
        # A foreign agent under the caller's own company is a plain 404.
        res = await route_world("GET", ITEM.format(company=co["acme"], agent=co["other_eve"]))
        assert res.status_code == 404

    async def test_a_caller_in_another_company_is_refused(self, co, route_world):
        for url in _all_urls(co):
            assert (await route_world("GET", url, "outsider")).status_code in (403, 404), url
        for url in _urls(co["acme"], co["acme_eve"]):
            assert (await route_world("GET", url, "outsider")).status_code == 403

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234"])
    async def test_malformed_company_is_a_validation_error(self, bad, co, route_world):
        for url in _urls(bad, co["acme_eve"]):
            assert (await route_world("GET", url)).status_code == 422


class TestPermissions:
    READERS = ("admin", "manager", "viewer", "api_key", "worker", "service_viewer")
    DENIED = ("employee", "run", "run_other", "guest", "unknown", "service_agent")

    @pytest.mark.parametrize("who", READERS)
    async def test_people_and_authorised_api_keys_read_agents(self, who, co, route_world):
        for url in _all_urls(co):
            res = await route_world("GET", url, who)
            assert res.status_code == 200, (who, url, res.text)

    @pytest.mark.parametrize("who", DENIED)
    async def test_every_other_principal_is_refused_on_all_three_routes(self, who, co, route_world):
        for url in _all_urls(co):
            res = await route_world("GET", url, who)
            assert res.status_code == 403, (who, url, res.text)
            assert str(co["acme_eve"]) not in res.text

    async def test_a_run_token_never_reads_the_full_agent_record(self, co, route_world):
        for who in ("run", "run_other"):
            for url in _all_urls(co):
                res = await route_world("GET", url, who)
                assert res.status_code == 403
                assert "autonomy_policy" not in res.text and "budget" not in res.text

    async def test_a_guest_and_a_human_agent_role_are_told_why(self, co, route_world):
        for who in ("guest", "employee"):
            for url in _all_urls(co):
                res = await route_world("GET", url, who)
                assert "may not read agent" in res.json()["detail"], (who, url)

    @pytest.mark.parametrize("name", ("inactive", "removed"))
    async def test_a_deactivated_or_removed_user_is_refused(self, name, co, route_world):
        if name == "inactive":
            await route_world.deactivate(name)
        else:
            await route_world.remove_membership(name)
        for url in _all_urls(co):
            assert (await route_world("GET", url, name)).status_code == 401, url

    async def test_an_anonymous_caller_is_refused(self, co, route_world):
        transport = httpx.ASGITransport(app=route_world.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as anon:
            for url in _all_urls(co):
                assert (await anon.get(url)).status_code == 401, url


class TestDirectItem:
    async def test_foreign_and_missing_ids_are_indistinguishable(self, co, route_world):
        missing = uuid.uuid4()
        for who in ("admin", "viewer", "api_key"):
            theirs = await route_world("GET", DIRECT.format(agent=co["other_eve"]), who)
            absent = await route_world("GET", DIRECT.format(agent=missing), who)
            assert theirs.status_code == absent.status_code == 404, who
            # The message echoes the id the caller asked for; nothing else may differ.
            echoed = theirs.text.replace(str(co["other_eve"]), str(missing))
            assert echoed == absent.text, who

    async def test_the_direct_route_serves_the_callers_company_only(self, co, route_world):
        mine = await route_world("GET", DIRECT.format(agent=co["acme_eve"]))
        assert mine.status_code == 200 and mine.json()["company_id"] == str(co["acme"])
        with _sql(co) as seen:
            await route_world("GET", DIRECT.format(agent=co["other_eve"]), "api_key")
        selects = [q for q in seen if "FROM agents" in q]
        assert selects and all("agents.company_id" in q for q in selects)

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234"])
    async def test_malformed_id_is_a_validation_error(self, bad, co, route_world):
        assert (await route_world("GET", DIRECT.format(agent=bad))).status_code == 422


STAMP = datetime(2026, 1, 1)


async def _fill(co, n):
    """``n`` agents created at one instant, so only the id can break ties."""
    async with co["db"]() as s:
        for i in range(n):
            s.add(
                Agent(
                    company_id=co["acme"],
                    name=f"bulk-{i}",
                    role="analyst",
                    adapter_type="openai",
                    model="gpt-x",
                    created_at=STAMP,
                    updated_at=STAMP,
                )
            )
        await s.commit()


class TestListPagination:
    def _url(self, co, query=""):
        return LIST.format(company=co["acme"]) + query

    async def test_default_and_maximum_bound_the_result(self, co, route_world):
        await _fill(co, 250)
        default = await route_world("GET", self._url(co))
        top = await route_world("GET", self._url(co, f"?limit={agent_routes.AGENT_PAGE_MAX}"))
        assert default.status_code == top.status_code == 200
        assert len(default.json()) == agent_routes.AGENT_PAGE_DEFAULT == 100
        assert len(top.json()) == agent_routes.AGENT_PAGE_MAX == 200

    @pytest.mark.parametrize(
        "query",
        ["?limit=0", "?limit=-1", "?limit=201", "?limit=abc", "?offset=-1", "?offset=x"],
    )
    async def test_invalid_paging_is_a_stable_422(self, query, co, route_world):
        res = await route_world("GET", self._url(co, query))
        assert res.status_code == 422, query
        assert res.json()["detail"][0]["loc"][0] == "query"

    async def test_pages_are_ordered_disjoint_and_complete(self, co, route_world):
        await _fill(co, 25)
        full = (await route_world("GET", self._url(co, "?limit=200"))).json()
        ids = [a["id"] for a in full]
        stamps = [a["created_at"] for a in full]
        assert stamps == sorted(stamps, reverse=True)
        tied = [a["id"] for a in full if a["created_at"].startswith("2026-01-01T00:00:00")]
        assert len(tied) == 25 and tied == sorted(tied, reverse=True)
        paged: list[str] = []
        for offset in range(0, len(ids), 7):
            page = await route_world("GET", self._url(co, f"?limit=7&offset={offset}"))
            assert len(page.json()) <= 7
            paged += [a["id"] for a in page.json()]
        assert paged == ids and len(set(paged)) == len(paged)

    async def test_limit_offset_and_order_are_applied_in_sql(self, co, route_world):
        await _fill(co, 12)
        with _sql(co) as seen:
            res = await route_world("GET", self._url(co, "?limit=5&offset=3"), "api_key")
        assert res.status_code == 200 and len(res.json()) == 5
        (query,) = [q for q in seen if "FROM agents" in q]
        assert "ORDER BY agents.created_at DESC, agents.id DESC" in query
        assert "LIMIT" in query and "OFFSET" in query

    async def test_status_filter_still_applies(self, co, route_world):
        await _fill(co, 3)
        res = await route_world("GET", self._url(co, "?status_filter=nothing-has-this"))
        assert res.status_code == 200 and res.json() == []


class TestStaticGuard:
    def _routes(self):
        return [r for r in agent_routes.router.routes if isinstance(r, APIRoute)]

    def _company_routes(self):
        return [r for r in self._routes() if "{company_id}" in r.path]

    def _gets(self):
        return [r for r in self._routes() if r.methods <= {"GET"}]

    def test_there_are_routes_to_check(self):
        assert len(self._company_routes()) == 4  # create, list, get, update
        assert len(self._gets()) == 3  # company list, company item, direct item

    def test_company_in_the_url_always_uses_the_path_company_dependency(self):
        for route in self._company_routes():
            assert get_scoped_company_id in _flatten(route.dependant), route.path

    def test_no_agent_route_binds_the_raw_path_company_itself(self):
        for route in self._company_routes():
            raw = {p.name for p in route.dependant.path_params}
            assert "company_id" not in raw, route.path

    def test_every_get_route_needs_read_agent_and_a_person_or_api_key(self):
        assert len(agent_routes.READ_AGENT) == 2
        for route in self._gets():
            for gate in agent_routes.READ_AGENT:
                assert gate in route.dependencies, route.path

    def test_every_get_route_is_bound_to_a_tenant(self):
        for route in self._gets():
            bound = set(_flatten(route.dependant))
            assert bound & {get_scoped_company_id, get_current_company_id}, route.path

    def test_every_get_route_has_a_bounded_response_model(self):
        for route in self._gets():
            model = route.response_model
            item = get_args(model)[0] if get_origin(model) is list else model
            assert isinstance(item, type) and issubclass(item, BaseModel), route.path
            assert item is not dict and item is not Any, route.path

    def test_list_routes_bound_their_pagination(self):
        lists = [r for r in self._gets() if get_origin(r.response_model) is list]
        assert len(lists) == 1
        for route in lists:
            params = {p.name: p for p in route.dependant.query_params}
            limit = params["limit"].field_info.metadata
            offset = params["offset"].field_info.metadata
            assert any(getattr(m, "ge", None) == 1 for m in limit), route.path
            assert any(0 < (getattr(m, "le", None) or 0) <= 200 for m in limit), route.path
            assert any(getattr(m, "ge", None) == 0 for m in offset), route.path
