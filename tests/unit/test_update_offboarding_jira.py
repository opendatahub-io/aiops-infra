"""Unit tests for the Jira update script using an offline Jira double."""

from __future__ import annotations

import contextlib
import io
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class FakeJiraError(Exception):
    def __init__(self, text: str = "Jira request failed", status_code: int | None = None):
        super().__init__(text)
        self.text = text
        self.status_code = status_code


# The unit-test environment intentionally does not install python-jira. This
# module double keeps imports offline while all script behavior remains real.
jira_module = types.ModuleType("jira")
jira_module.__path__ = []
jira_module.JIRA = Mock(name="JIRA")
jira_exceptions = types.ModuleType("jira.exceptions")
jira_exceptions.JIRAError = FakeJiraError
jira_module.exceptions = jira_exceptions
with patch.dict(sys.modules, {"jira": jira_module, "jira.exceptions": jira_exceptions}):
    import update_offboarding_jira as script  # noqa: E402


def issue(
    *,
    key: str = "RHOAIENG-1234",
    labels: list[str] | None = None,
    attachments: list[SimpleNamespace] | None = None,
    status: str = "Open",
    description: str | None = "Template description",
) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        fields=SimpleNamespace(
            labels=list(labels or []),
            attachment=list(attachments or []),
            status=SimpleNamespace(name=status),
            project=SimpleNamespace(key="RHAI"),
            summary="Template summary",
            issuetype=SimpleNamespace(name="Task"),
            description=description,
        ),
        update=Mock(name="issue.update"),
    )


def jira_double() -> SimpleNamespace:
    return SimpleNamespace(
        issue=Mock(name="jira.issue"),
        create_issue=Mock(name="jira.create_issue"),
        create_issue_link=Mock(name="jira.create_issue_link"),
        add_comment=Mock(name="jira.add_comment"),
        delete_attachment=Mock(name="jira.delete_attachment"),
        add_attachment=Mock(name="jira.add_attachment"),
        myself=Mock(name="jira.myself"),
        transitions=Mock(name="jira.transitions"),
        transition_issue=Mock(name="jira.transition_issue"),
    )


class TestClientAndIssueHelpers(unittest.TestCase):
    def test_client_requires_email(self):
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as raised:
                script.get_jira_client()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("JIRA_USER_EMAIL", err.getvalue())

    def test_client_requires_token(self):
        with patch.dict("os.environ", {"JIRA_USER_EMAIL": "person@example.com"}, clear=True):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as raised:
                    script.get_jira_client()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("JIRA_API_TOKEN", err.getvalue())

    def test_client_uses_default_and_configured_server(self):
        credentials = {"JIRA_USER_EMAIL": "person@example.com", "JIRA_API_TOKEN": "secret"}
        for environment, server in ((credentials, script.DEFAULT_JIRA_SERVER), ({**credentials, "JIRA_SERVER": "https://jira.example"}, "https://jira.example")):
            with self.subTest(server=server), patch.dict("os.environ", environment, clear=True), patch.object(script, "JIRA", return_value="client") as jira:
                self.assertEqual(script.get_jira_client(), "client")
                jira.assert_called_once_with(server=server, basic_auth=("person@example.com", "secret"))

    def test_extracts_key_from_url_or_key(self):
        self.assertEqual(script.extract_issue_id(" https://jira.example/browse/RHAI-12/ "), "RHAI-12")
        self.assertEqual(script.extract_issue_id("RHAI-13"), "RHAI-13")

    def test_fetch_issue_returns_issue(self):
        jira = jira_double()
        expected = issue()
        jira.issue.return_value = expected
        self.assertIs(script.fetch_issue(jira, "RHAI-1"), expected)
        jira.issue.assert_called_once_with("RHAI-1")

    def test_fetch_issue_reports_known_and_unknown_jira_errors(self):
        cases = (
            (401, "Authentication failed (HTTP 401)."),
            (403, "Access denied (HTTP 403)."),
            (404, "Issue not found (HTTP 404): RHAI-1."),
            (503, "Failed to fetch RHAI-1 (HTTP 503): unavailable"),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                jira = jira_double()
                jira.issue.side_effect = FakeJiraError("unavailable", status)
                with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as raised:
                    script.fetch_issue(jira, "RHAI-1")
                self.assertEqual(raised.exception.code, 1)
                self.assertIn(expected, err.getvalue())

    def test_fetch_issue_reports_unexpected_errors(self):
        jira = jira_double()
        jira.issue.side_effect = RuntimeError("connection reset")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.fetch_issue(jira, "RHAI-1")
        self.assertIn("Unexpected error fetching RHAI-1: connection reset", err.getvalue())


class TestIssueMutations(unittest.TestCase):
    def test_clone_copies_description_and_stops_after_first_link_name(self):
        jira = jira_double()
        source = issue(key="RHAI-1")
        clone = issue(key="RHAI-2")
        with patch.object(script, "fetch_issue", return_value=source):
            jira.create_issue.return_value = clone
            self.assertEqual(script.clone_issue(jira, "RHAI-1"), "RHAI-2")
        jira.create_issue.assert_called_once_with(fields={
            "project": {"key": "RHAI"},
            "summary": "Template summary",
            "issuetype": {"name": "Task"},
            "description": "Template description",
        })
        jira.create_issue_link.assert_called_once_with("Cloners", "RHAI-2", "RHAI-1")

    def test_clone_omits_empty_description_and_tries_link_aliases(self):
        jira = jira_double()
        source = issue(key="RHAI-1", description="")
        clone = issue(key="RHAI-2")
        jira.create_issue_link.side_effect = [FakeJiraError(), None]
        with patch.object(script, "fetch_issue", return_value=source):
            jira.create_issue.return_value = clone
            self.assertEqual(script.clone_issue(jira, "RHAI-1"), "RHAI-2")
        self.assertNotIn("description", jira.create_issue.call_args.kwargs["fields"])
        self.assertEqual(jira.create_issue_link.call_args_list, [
            call("Cloners", "RHAI-2", "RHAI-1"),
            call("cloners", "RHAI-2", "RHAI-1"),
        ])

    def test_clone_warns_when_no_link_alias_exists_but_returns_created_key(self):
        jira = jira_double()
        source = issue(key="RHAI-1")
        clone = issue(key="RHAI-2")
        jira.create_issue_link.side_effect = FakeJiraError("unknown link type")
        with patch.object(script, "fetch_issue", return_value=source), contextlib.redirect_stderr(io.StringIO()) as err:
            jira.create_issue.return_value = clone
            self.assertEqual(script.clone_issue(jira, "RHAI-1"), "RHAI-2")
        self.assertEqual(jira.create_issue_link.call_count, 4)
        self.assertIn("WARN: Could not set 'Cloners' link", err.getvalue())

    def test_clone_reports_create_error(self):
        jira = jira_double()
        with patch.object(script, "fetch_issue", return_value=issue()), contextlib.redirect_stderr(io.StringIO()) as err:
            jira.create_issue.side_effect = FakeJiraError("create denied")
            with self.assertRaises(SystemExit) as raised:
                script.clone_issue(jira, "RHAI-1")
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Failed to clone RHAI-1: create denied", err.getvalue())

    def test_title_and_description_updates(self):
        jira = jira_double()
        target = issue()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.set_title(jira, target, "Updated")
            script.set_description(jira, target, "Details")
        self.assertEqual(target.update.call_args_list, [
            call(fields={"summary": "Updated"}),
            call(fields={"description": "Details"}),
        ])
        self.assertIn("Title set: 'Updated'", err.getvalue())
        self.assertIn("Description updated (7 chars)", err.getvalue())

    def test_title_and_description_report_jira_errors(self):
        for operation, expected in ((script.set_title, "Failed to set title"), (script.set_description, "Failed to set description")):
            with self.subTest(operation=operation.__name__), contextlib.redirect_stderr(io.StringIO()) as err:
                target = issue()
                target.update.side_effect = FakeJiraError("edit denied")
                with self.assertRaises(SystemExit):
                    operation(jira_double(), target, "Updated")
            self.assertIn(expected, err.getvalue())

    def test_related_link_tries_alias_after_first_error(self):
        jira = jira_double()
        target = issue()
        jira.create_issue_link.side_effect = [FakeJiraError(), None]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.link_related(jira, target, "https://jira.example/browse/RHAI-77")
        self.assertEqual(jira.create_issue_link.call_args_list, [
            call("Relates", target.key, "RHAI-77"),
            call("relates to", target.key, "RHAI-77"),
        ])
        self.assertIn("Linked 'RHOAIENG-1234' relates to 'RHAI-77'", err.getvalue())

    def test_related_link_reports_when_all_aliases_fail(self):
        jira = jira_double()
        jira.create_issue_link.side_effect = FakeJiraError("unknown type")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as raised:
            script.link_related(jira, issue(), "RHAI-77")
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(jira.create_issue_link.call_count, 4)
        self.assertIn("Could not create 'relates to' link", err.getvalue())

    def test_reporter_uses_cloud_account_id(self):
        jira = jira_double()
        jira.myself.return_value = {"accountId": "account-1", "displayName": "Person"}
        target = issue()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.set_reporter_to_current(jira, target)
        target.update.assert_called_once_with(fields={"reporter": {"accountId": "account-1"}})
        self.assertIn("Reporter set to current user: Person", err.getvalue())

    def test_reporter_falls_back_to_name_then_key(self):
        for myself, expected in (({"name": "legacy-user", "displayName": "Legacy"}, {"name": "legacy-user"}), ({"key": "legacy-key"}, {"name": "legacy-key"}), ({}, {"name": None})):
            with self.subTest(myself=myself), contextlib.redirect_stderr(io.StringIO()):
                jira = jira_double()
                jira.myself.return_value = myself
                target = issue()
                script.set_reporter_to_current(jira, target)
            target.update.assert_called_once_with(fields={"reporter": expected})

    def test_reporter_reports_jira_error(self):
        jira = jira_double()
        jira.myself.side_effect = FakeJiraError("profile denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.set_reporter_to_current(jira, issue())
        self.assertIn("Failed to set reporter: profile denied", err.getvalue())

    def test_add_labels_preserves_existing_labels_and_applies_both_once(self):
        target = issue(labels=["keep-me"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.add_labels(jira_double(), target, ["offboarding-yaml-attached", "component-offboarding"])
        target.update.assert_called_once_with(fields={"labels": [
            "keep-me", "offboarding-yaml-attached", "component-offboarding",
        ]})
        self.assertIn("Label added: 'offboarding-yaml-attached'", err.getvalue())
        self.assertIn("Label added: 'component-offboarding'", err.getvalue())

    def test_add_labels_skips_existing_and_duplicate_labels(self):
        target = issue(labels=["already"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.add_labels(jira_double(), target, ["already", "new", "new"])
        target.update.assert_called_once_with(fields={"labels": ["already", "new"]})
        self.assertEqual(err.getvalue().count("Label 'already' is already present"), 1)
        self.assertEqual(err.getvalue().count("Label 'new' is already present"), 1)

    def test_add_labels_does_not_update_when_all_labels_exist(self):
        target = issue(labels=["one", "two"])
        with contextlib.redirect_stderr(io.StringIO()):
            script.add_labels(jira_double(), target, ["one", "two"])
        target.update.assert_not_called()

    def test_add_labels_reports_update_error(self):
        target = issue()
        target.update.side_effect = FakeJiraError("label denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.add_labels(jira_double(), target, ["one", "two"])
        self.assertIn("Failed to add labels ['one', 'two']: label denied", err.getvalue())

    def test_remove_label_skips_missing_label_and_removes_present_label(self):
        jira = jira_double()
        target = issue(labels=["keep", "remove"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.remove_label(jira, target, "missing")
            script.remove_label(jira, target, "remove")
        target.update.assert_called_once_with(fields={"labels": ["keep"]})
        self.assertIn("Label 'missing' is not present — skipping", err.getvalue())
        self.assertIn("Label removed: 'remove'", err.getvalue())

    def test_remove_label_reports_update_error(self):
        target = issue(labels=["remove"])
        target.update.side_effect = FakeJiraError("label denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.remove_label(jira_double(), target, "remove")
        self.assertIn("Failed to remove label 'remove': label denied", err.getvalue())

    def test_comment_reports_short_and_truncated_long_preview(self):
        jira = jira_double()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.add_comment(jira, issue(), "short")
            script.add_comment(jira, issue(), "x" * 81)
        self.assertEqual(jira.add_comment.call_args_list, [call(unittest.mock.ANY, "short"), call(unittest.mock.ANY, "x" * 81)])
        self.assertIn('Comment posted: "short"', err.getvalue())
        self.assertIn('Comment posted: "' + "x" * 80 + '…"', err.getvalue())

    def test_comment_reports_jira_error(self):
        jira = jira_double()
        jira.add_comment.side_effect = FakeJiraError("comments denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.add_comment(jira, issue(), "comment")
        self.assertIn("Failed to post comment: comments denied", err.getvalue())


class TestAttachmentAndTransition(unittest.TestCase):
    def test_attachment_rejects_missing_path_and_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path, expected in ((root / "missing.yaml", "File not found"), (root, "Not a file")):
                with self.subTest(path=path), contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                    script.attach_file(jira_double(), issue(), path)
                self.assertIn(expected, err.getvalue())

    def test_attachment_deletes_matching_files_and_uploads_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "details.yaml"
            path.write_text("abc", encoding="utf-8")
            target = issue(attachments=[
                SimpleNamespace(filename="other.yaml", id="1"),
                SimpleNamespace(filename="details.yaml", id="2"),
            ])
            jira = jira_double()
            with contextlib.redirect_stderr(io.StringIO()) as err:
                script.attach_file(jira, target, path)
            jira.delete_attachment.assert_called_once_with("2")
            jira.add_attachment.assert_called_once_with(issue=target.key, attachment=str(path))
            self.assertIn("Deleted existing attachment 'details.yaml' (id=2)", err.getvalue())
            self.assertIn("Attached 'details.yaml' (3 bytes)", err.getvalue())

    def test_attachment_uploads_when_no_matching_file_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "details.yaml"
            path.write_text("", encoding="utf-8")
            jira = jira_double()
            with contextlib.redirect_stderr(io.StringIO()) as err:
                script.attach_file(jira, issue(attachments=[SimpleNamespace(filename="other.yaml", id="1")]), path)
            jira.delete_attachment.assert_not_called()
            self.assertIn("No existing 'details.yaml' attachment found", err.getvalue())
            self.assertIn("Attached 'details.yaml' (0 bytes)", err.getvalue())

    def test_attachment_reports_delete_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "details.yaml"
            path.write_text("abc", encoding="utf-8")
            jira = jira_double()
            jira.delete_attachment.side_effect = FakeJiraError("delete denied")
            target = issue(attachments=[SimpleNamespace(filename=path.name, id="7")])
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                script.attach_file(jira, target, path)
            self.assertIn("Failed to delete attachment 'details.yaml' (id=7): delete denied", err.getvalue())
            jira.add_attachment.assert_not_called()

    def test_attachment_reports_jira_and_unexpected_upload_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "details.yaml"
            path.write_text("abc", encoding="utf-8")
            cases = ((FakeJiraError("upload denied"), "Failed to attach 'details.yaml': upload denied"), (OSError("disk error"), "Unexpected error attaching 'details.yaml': disk error"))
            for error, expected in cases:
                with self.subTest(error=error), contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                    jira = jira_double()
                    jira.add_attachment.side_effect = error
                    script.attach_file(jira, issue(), path)
                self.assertIn(expected, err.getvalue())

    def test_transition_skips_when_target_status_already_matches_case_insensitively(self):
        jira = jira_double()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.transition_status(jira, issue(status="In Progress"), "in progress")
        jira.transitions.assert_not_called()
        self.assertIn("Status is already 'In Progress'", err.getvalue())

    def test_transition_reports_fetch_error(self):
        jira = jira_double()
        jira.transitions.side_effect = FakeJiraError("transition lookup denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.transition_status(jira, issue(), "Done")
        self.assertIn("Failed to fetch transitions: transition lookup denied", err.getvalue())

    def test_transition_reports_sorted_available_choices_when_no_match(self):
        jira = jira_double()
        jira.transitions.return_value = [
            {"id": "2", "to": {"name": "Review"}},
            {"id": "1", "to": {"name": "In Progress"}},
        ]
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.transition_status(jira, issue(), "Done")
        output = err.getvalue()
        self.assertLess(output.index("- In Progress"), output.index("- Review"))
        jira.transition_issue.assert_not_called()

    def test_transition_uses_case_insensitive_match_and_reports_success(self):
        jira = jira_double()
        jira.transitions.return_value = [{"id": "7", "to": {"name": "Done"}}]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            script.transition_status(jira, issue(), "done")
        jira.transition_issue.assert_called_once_with(unittest.mock.ANY, "7")
        self.assertIn("Status transitioned: 'Open' → 'Done'", err.getvalue())

    def test_transition_reports_update_error(self):
        jira = jira_double()
        jira.transitions.return_value = [{"id": "7", "to": {"name": "Done"}}]
        jira.transition_issue.side_effect = FakeJiraError("transition denied")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            script.transition_status(jira, issue(), "Done")
        self.assertIn("Failed to transition to 'Done': transition denied", err.getvalue())


class TestCommandLine(unittest.TestCase):
    def run_main(self, args: list[str]) -> None:
        with patch.object(sys, "argv", ["update_offboarding_jira.py", *args]):
            script.main()

    def test_rejects_clone_mode_without_source(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.run_main(["new"])
        self.assertEqual(raised.exception.code, 2)

    def test_rejects_clone_source_for_existing_issue(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.run_main(["RHAI-1", "--clone-from", "RHAI-2"])
        self.assertEqual(raised.exception.code, 2)

    def test_rejects_existing_issue_without_actions(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.run_main(["RHAI-1"])
        self.assertEqual(raised.exception.code, 2)

    def test_existing_issue_dispatches_all_options_and_both_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            attachment = Path(temp) / "details.yaml"
            attachment.write_text("yaml", encoding="utf-8")
            jira = jira_double()
            target = issue(labels=["remove-me"])
            jira.issue.return_value = target
            jira.myself.return_value = {"accountId": "account-1", "displayName": "Person"}
            jira.transitions.return_value = [{"id": "3", "to": {"name": "In Progress"}}]
            with patch.object(script, "get_jira_client", return_value=jira), patch.object(sys, "argv", [
                "update_offboarding_jira.py", "https://jira.example/browse/RHAI-1",
                "--set-title", "New title", "--set-description", "New description",
                "--link-related", "RHAI-2", "--set-reporter-to-current",
                "--add-label", "offboarding-yaml-attached", "--add-label", "component-offboarding",
                "--remove-label", "remove-me", "--comment", "Ready", "--status", "In Progress",
                "--attach", str(attachment),
            ]), contextlib.redirect_stderr(io.StringIO()) as err:
                script.main()
        self.assertEqual(jira.issue.call_args.args, ("RHAI-1",))
        label_updates = [
            update.kwargs["fields"]["labels"]
            for update in target.update.call_args_list
            if "labels" in update.kwargs["fields"]
        ]
        self.assertEqual(label_updates, [
            ["remove-me", "offboarding-yaml-attached", "component-offboarding"],
            ["offboarding-yaml-attached", "component-offboarding"],
        ])
        jira.add_comment.assert_called_once_with(target, "Ready")
        jira.transition_issue.assert_called_once_with(target, "3")
        self.assertIn("Done. Issue RHOAIENG-1234 updated successfully.", err.getvalue())

    def test_existing_issue_dispatches_single_label_without_other_actions(self):
        jira = jira_double()
        target = issue()
        jira.issue.return_value = target
        with patch.object(script, "get_jira_client", return_value=jira), patch.object(sys, "argv", ["update_offboarding_jira.py", "RHAI-1", "--add-label", "hello"]), contextlib.redirect_stderr(io.StringIO()):
            script.main()
        jira.add_comment.assert_not_called()
        target.update.assert_called_once_with(fields={"labels": ["hello"]})
        jira.create_issue_link.assert_not_called()
        jira.transitions.assert_not_called()

    def test_new_issue_clones_then_updates_the_created_issue(self):
        jira = jira_double()
        source = issue(key="RHAI-1")
        created = issue(key="RHAI-2")
        jira.issue.side_effect = [source, created]
        jira.create_issue.return_value = created
        with patch.object(script, "get_jira_client", return_value=jira), patch.dict("os.environ", {"JIRA_SERVER": "https://jira.example"}), patch.object(sys, "argv", [
            "update_offboarding_jira.py", "new", "--clone-from", "RHAI-1", "--comment", "Created",
        ]), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            script.main()
        self.assertEqual(out.getvalue().strip(), "https://jira.example/browse/RHAI-2")
        jira.add_comment.assert_called_once_with(created, "Created")
        self.assertIn("Issue RHAI-2 created and updated successfully.", err.getvalue())

    def test_script_entrypoint_runs_main(self):
        jira = jira_double()
        target = issue()
        jira.issue.return_value = target
        jira_module.JIRA.return_value = jira
        with patch.dict(sys.modules, {"jira": jira_module, "jira.exceptions": jira_exceptions}), patch.dict("os.environ", {"JIRA_USER_EMAIL": "person@example.com", "JIRA_API_TOKEN": "secret"}, clear=True), patch.object(sys, "argv", [
            str(REPO_ROOT / "scripts" / "update_offboarding_jira.py"), "RHAI-1", "--comment", "entrypoint",
        ]), contextlib.redirect_stderr(io.StringIO()) as err:
            runpy.run_path(str(REPO_ROOT / "scripts" / "update_offboarding_jira.py"), run_name="__main__")
        jira.add_comment.assert_called_once_with(target, "entrypoint")
        self.assertIn("Issue RHOAIENG-1234 updated successfully.", err.getvalue())


if __name__ == "__main__":
    unittest.main()
