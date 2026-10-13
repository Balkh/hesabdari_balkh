from django.urls import path

from . import landed_cost_views

urlpatterns = [
    path("landed-costs/", landed_cost_views.landed_cost_collection, name="landed-cost-collection"),
    path("landed-costs/<int:pk>/", landed_cost_views.landed_cost_detail, name="landed-cost-detail"),
    path("landed-costs/<int:pk>/post/", landed_cost_views.landed_cost_post, name="landed-cost-post"),
]
