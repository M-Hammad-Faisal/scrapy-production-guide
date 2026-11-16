from django.urls import path

from manual_entry import views

urlpatterns = [
    path("api/prices/", views.PriceCreateView.as_view()),
    path("api/prices/bulk/", views.PriceBulkView.as_view()),
]
