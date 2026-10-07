from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render

from .forms import RegistrationForm
from .services import create_registration


@login_not_required
def register(request):
    if request.user.is_authenticated:
        return redirect("demands:home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            create_registration(form)
            return render(request, "registration/registration_submitted.html")
    else:
        form = RegistrationForm()
    return render(request, "registration/register.html", {"form": form})
