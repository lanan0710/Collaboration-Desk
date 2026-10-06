from django.contrib.auth.decorators import login_required
from django.shortcuts import render

#只有已登录成功的用户才执行home函数，否则跳转到登录页面
@login_required
def home(request):
    return render(request, "demands/home.html")