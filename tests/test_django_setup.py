from django.core.management import call_command


def test_django_check():
    call_command("check")
