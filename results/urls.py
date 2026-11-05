from django.urls import path
from .views import results_browse_view, upload_pdf_view, races_list_view

urlpatterns = [
    path('', results_browse_view, name='browse_results'),
    path('races/', races_list_view, name='list_races'),
    path('upload/', upload_pdf_view, name='upload_pdf'),
]
