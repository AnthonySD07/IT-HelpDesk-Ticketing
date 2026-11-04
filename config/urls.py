from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from tickets import views
from tickets.forms import LoginForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.ticket_list, name='ticket_list'),
    path('tickets/new/', views.ticket_create, name='ticket_create'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/assign/', views.ticket_assign, name='ticket_assign'),
    path('tickets/<int:pk>/status/', views.ticket_status, name='ticket_status'),
    path('reports/', views.reports, name='reports'),
    path('login/', auth_views.LoginView.as_view(authentication_form=LoginForm), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)