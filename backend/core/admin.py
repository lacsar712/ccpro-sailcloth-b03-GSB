from django.contrib import admin

from .models import ClothRoll, DipRun, Loft


@admin.register(ClothRoll)
class ClothRollAdmin(admin.ModelAdmin):
    list_display = ("roll_code", "loft", "status", "cool_down_full", "fabric_weight_gsm")
    list_filter = ("status", "cool_down_full", "loft")
    list_editable = ("cool_down_full",)


admin.site.register(Loft)
admin.site.register(DipRun)
