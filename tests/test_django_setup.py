import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_django_check():
    call_command("check")
