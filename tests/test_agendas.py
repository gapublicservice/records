import unittest

from harvester.agendas import agenda_files, dockets_in, label_for


class AgendaTests(unittest.TestCase):
    def test_files_from_event_page(self):
        page = ('<a href="/site/assets/files/9196/11-12-26_telecom_agenda.doc">a</a>'
                '<a href="https://psc.ga.gov/site/assets/files/9196/11-12-26_amended_energy_agenda.doc">b</a>'
                '<a href="/site/assets/files/9196/11-12-26_telecom_agenda.doc">again</a>')
        got = agenda_files(page)
        self.assertEqual([f["name"] for f in got], ["11-12-26_telecom_agenda.doc", "11-12-26_amended_energy_agenda.doc"])
        self.assertTrue(all(f["url"].startswith("https://psc.ga.gov/site/assets/files/9196/") for f in got))

    def test_labels(self):
        self.assertEqual(label_for("11-17-26_admin__session_agenda.doc"), "Administrative session")
        self.assertEqual(label_for("11-17-2026_admin_affairs_agenda_admin.doc"), "Administrative Affairs committee")
        self.assertEqual(label_for("11-12-26_amended_energy_agenda.doc"), "Amended energy committee")

    def test_dockets_need_the_word_docket(self):
        got = dockets_in("1. DOCKET NO. 56298 Georgia Power IRP\n2. Approval of minutes, 30334\n"
                         "3. Docket Nos. 44280 and 44281: rate case")
        self.assertEqual([i["docket"] for i in got], [44280, 44281, 56298])


if __name__ == "__main__":
    unittest.main()
