"""The company-in-the-URL Agent read routes: list and get.

Both take ``PathCompanyId`` and ``read:agent``. A company that is not the caller's, existing or
not, is the same 403 in every UUID spelling, and no Agent query runs for it. The caller's own
company never stands in for a rejected one.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute

from nexus.api.deps import get_scoped_company_id
from nexus.api.routes import agents as agent_routes
from tests.test_agent_route_security import route_world  # noqa: F401 -- fixture
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_goal_route_security import _sql
from tests.test_task_route_security import FORMS, _flatten
from tests.test_work_service import co  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

LIST = "/api/v1/companies/{company}/agents"
ITEM = "/api/v1/companies/{company}/agents/{agent}"


def _urls(company, agent):
    return (LIST.format(company=company), ITEM.format(company=company, agent=agent))


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
        for url in _urls(co["acme"], co["acme_eve"]):
            assert (await route_world("GET", url, "outsider")).status_code == 403

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234"])
    async def test_malformed_company_is_a_validation_error(self, bad, co, route_world):
        for url in _urls(bad, co["acme_eve"]):
            assert (await route_world("GET", url)).status_code == 422


class TestPermissions:
    @pytest.mark.parametrize(
        "who", ("admin", "manager", "viewer", "employee", "run", "run_other", "api_key", "worker")
    )
    async def test_agent_readers(self, who, co, route_world):
        for url in _urls(co["acme"], co["acme_eve"]):
            res = await route_world("GET", url, who)
            assert res.status_code == 200, (who, url, res.text)

    async def test_a_principal_without_read_agent_is_refused(self, co, route_world):
        for url in _urls(co["acme"], co["acme_eve"]):
            res = await route_world("GET", url, "guest")
            assert res.status_code == 403, url
            assert "may not read agent" in res.json()["detail"]

    @pytest.mark.parametrize("name", ("inactive", "removed"))
    async def test_a_deactivated_or_removed_user_is_refused(self, name, co, route_world):
        if name == "inactive":
            await route_world.deactivate(name)
        else:
            await route_world.remove_membership(name)
        for url in _urls(co["acme"], co["acme_eve"]):
            assert (await route_world("GET", url, name)).status_code == 401, url


class TestStaticGuard:
    def _company_routes(self):
        return [
            r
            for r in agent_routes.router.routes
            if isinstance(r, APIRoute) and "{company_id}" in r.path
        ]

    def test_there_are_company_routes_to_check(self):
        assert len(self._company_routes()) == 4  # create, list, get, update

    def test_company_in_the_url_always_uses_the_path_company_dependency(self):
        for route in self._company_routes():
            assert get_scoped_company_id in _flatten(route.dependant), route.path

    def test_no_agent_route_binds_the_raw_path_company_itself(self):
        for route in self._company_routes():
            raw = {p.name for p in route.dependant.path_params}
            assert "company_id" not in raw, route.path

    def test_every_company_get_route_needs_read_agent(self):
        gets = [r for r in self._company_routes() if r.methods <= {"GET"}]
        assert len(gets) == 2
        for route in gets:
            assert route.dependencies is not None
            assert agent_routes.READ_AGENT[0] in route.dependencies, route.path
