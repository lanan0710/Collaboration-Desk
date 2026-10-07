from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseFormSet, formset_factory

from .attachment_rules import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    validate_http_result_url,
    validate_submission_materials,
)
from .models import Review


User = get_user_model()


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        if user.email:
            return f"{user.username}（{user.email}）"
        return user.username


class RequirementContentForm(forms.Form):
    title = forms.CharField(
        label="需求标题",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "例如：支持按状态筛选需求"}),
    )
    description = forms.CharField(
        label="需求说明",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "说明背景、目标和需要解决的问题",
            }
        ),
    )


class RequirementCreateForm(RequirementContentForm):
    assignee = UserChoiceField(
        label="负责人",
        queryset=User.objects.none(),
        empty_label="请选择负责人",
        error_messages={
            "required": "请选择负责人。",
            "invalid_choice": "请选择一个有效的负责人。",
        },
    )

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        queryset = User.objects.filter(is_active=True).order_by("username")
        if actor and actor.is_authenticated:
            queryset = queryset.exclude(pk=actor.pk)
        self.fields["assignee"].queryset = queryset


class RequirementEditForm(RequirementContentForm):
    lock_version = forms.IntegerField(
        label="数据版本",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少需求数据版本，请刷新页面后重试。",
            "invalid": "需求数据版本无效，请刷新页面后重试。",
            "min_value": "需求数据版本无效，请刷新页面后重试。",
        },
    )


class CriterionForm(forms.Form):
    content = forms.CharField(
        label="验收条件",
        max_length=500,
        error_messages={
            "required": "请填写这条验收条件。",
            "max_length": "每条验收条件不能超过 500 个字符。",
        },
        widget=forms.TextInput(attrs={"placeholder": "填写一条可明确判断是否通过的条件"}),
    )


class BaseCriterionFormSet(BaseFormSet):
    default_error_messages = {
        **BaseFormSet.default_error_messages,
        "too_many_forms": "验收条件最多填写 20 条。",
        "too_few_forms": "至少需要填写一条验收条件。",
    }


CriterionFormSet = formset_factory(
    CriterionForm,
    formset=BaseCriterionFormSet,
    extra=0,
    min_num=1,
    max_num=20,
    absolute_max=20,
    validate_min=True,
    validate_max=True,
)


class StartRequirementForm(forms.Form):
    lock_version = forms.IntegerField(
        label="数据版本",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少需求数据版本，请刷新页面后重试。",
            "invalid": "需求数据版本无效，请刷新页面后重试。",
            "min_value": "需求数据版本无效，请刷新页面后重试。",
        },
    )


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class SubmissionForm(forms.Form):
    result_url = forms.URLField(
        label="成果链接",
        required=True,
        max_length=1000,
        validators=[validate_http_result_url],
        error_messages={
            "required": "必须填写成果链接。",
            "invalid": "请输入有效的 HTTP/HTTPS 成果链接。",
            "max_length": "成果链接不能超过 1000 个字符。",
        },
        widget=forms.URLInput(
            attrs={"placeholder": "https://example.com/result"}
        ),
    )
    description = forms.CharField(
        label="完成说明",
        error_messages={"required": "请填写完成说明。"},
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "说明本次提交完成的内容、验证方式和注意事项",
            }
        ),
    )
    attachments = MultipleFileField(
        label="成果附件（可选）",
        required=False,
        help_text="最多 5 个文档、图片或压缩包；单个不超过 20 MiB，合计不超过 50 MiB。",
        widget=MultipleFileInput(
            attrs={
                "multiple": True,
                "accept": ",".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS)),
            }
        ),
    )
    lock_version = forms.IntegerField(
        label="数据版本",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少需求数据版本，请刷新页面后重试。",
            "invalid": "需求数据版本无效，请刷新页面后重试。",
            "min_value": "需求数据版本无效，请刷新页面后重试。",
        },
    )
    idempotency_key = forms.UUIDField(
        label="幂等请求标识",
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少请求标识，请刷新页面后重试。",
            "invalid": "请求标识无效，请刷新页面后重试。",
        },
    )

    def clean(self):
        cleaned_data = super().clean()
        if "result_url" in self.errors or "attachments" in self.errors:
            return cleaned_data

        try:
            result_url, attachments = validate_submission_materials(
                cleaned_data.get("result_url"),
                cleaned_data.get("attachments"),
            )
        except forms.ValidationError as exc:
            self.add_error(None, exc)
        else:
            cleaned_data["result_url"] = result_url
            cleaned_data["attachments"] = attachments
        return cleaned_data


class ReviewDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label="审核结论",
        choices=Review.Decision.choices,
        error_messages={
            "required": "请选择审核结论。",
            "invalid_choice": "请选择有效的审核结论。",
        },
        widget=forms.RadioSelect(),
    )
    return_reason = forms.CharField(
        label="退回总说明",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "退回时请说明需要修改的内容",
            }
        ),
    )
    lock_version = forms.IntegerField(
        label="数据版本",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少需求数据版本，请刷新页面后重试。",
            "invalid": "需求数据版本无效，请刷新页面后重试。",
            "min_value": "需求数据版本无效，请刷新页面后重试。",
        },
    )
    submission_id = forms.IntegerField(
        label="成果提交",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少待审核的成果提交，请刷新页面后重试。",
            "invalid": "成果提交无效，请刷新页面后重试。",
            "min_value": "成果提交无效，请刷新页面后重试。",
        },
    )
    idempotency_key = forms.UUIDField(
        label="幂等请求标识",
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少请求标识，请刷新页面后重试。",
            "invalid": "请求标识无效，请刷新页面后重试。",
        },
    )

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get("decision")
        return_reason = cleaned_data.get("return_reason", "").strip()

        if decision == Review.Decision.RETURNED and not return_reason:
            self.add_error("return_reason", "退回时必须填写具体修改原因。")
        elif decision == Review.Decision.APPROVED and return_reason:
            self.add_error("return_reason", "通过时不应填写退回原因。")

        cleaned_data["return_reason"] = return_reason
        return cleaned_data


class ReviewCriterionForm(forms.Form):
    criterion_id = forms.IntegerField(
        label="验收条件",
        min_value=1,
        widget=forms.HiddenInput(),
        error_messages={
            "required": "缺少验收条件，请刷新页面后重试。",
            "invalid": "验收条件无效，请刷新页面后重试。",
            "min_value": "验收条件无效，请刷新页面后重试。",
        },
    )
    criterion_text = forms.CharField(
        label="验收条件",
        disabled=True,
        error_messages={"required": "验收条件内容缺失，请刷新页面后重试。"},
    )
    passed = forms.TypedChoiceField(
        label="检查结果",
        choices=(("true", "通过"), ("false", "未通过")),
        coerce=lambda value: value == "true",
        empty_value=None,
        widget=forms.RadioSelect(),
        error_messages={
            "required": "请选择这条验收条件是否通过。",
            "invalid_choice": "请选择有效的检查结果。",
        },
    )
    comment = forms.CharField(
        label="检查说明",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "未通过时必须说明具体问题和修改要求",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        passed = cleaned_data.get("passed")
        comment = cleaned_data.get("comment", "").strip()

        if passed is False and not comment:
            self.add_error("comment", "未通过项必须填写具体修改说明。")

        cleaned_data["comment"] = comment
        return cleaned_data


class BaseReviewCriterionFormSet(BaseFormSet):
    default_error_messages = {
        **BaseFormSet.default_error_messages,
        "too_many_forms": "验收条件最多只能审核 20 条。",
    }


ReviewCriterionFormSet = formset_factory(
    ReviewCriterionForm,
    formset=BaseReviewCriterionFormSet,
    extra=0,
    max_num=20,
    absolute_max=20,
    validate_max=True,
)
