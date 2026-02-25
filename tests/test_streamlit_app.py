from streamlit.testing.v1 import AppTest


def test_main_title_present():
    """App shows the main title on initial load."""
    at = AppTest.from_file("app.py")
    at.run()
    # The app defines the main title as 'reMarkable Manager'
    assert at.title and any(t.value == "reMarkable Manager" for t in at.title)


def test_configuration_save_requires_name():
    """Switch to Configuration and click Save without name."""
    at = AppTest.from_file("app.py")
    # Initial run to populate the element tree and imports
    at.run()

    # Select the Configuration page from the sidebar and re-run
    at.sidebar.radio[0].set_value(":material/settings: Configuration").run()

    # Click the first "Sauvegarder" button (create-new-device path) and run
    at.button[0].click().run()

    # An error should be shown asking for a device name
    assert at.error and any("Veuillez donner un nom" in e.value for e in at.error)
