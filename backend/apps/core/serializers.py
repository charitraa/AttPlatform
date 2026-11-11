from rest_framework import serializers


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    version = serializers.CharField()
    timestamp = serializers.DateTimeField()


class DependencyCheckSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "error"])
    latency_ms = serializers.FloatField()


class ReadinessSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    checks = serializers.DictField(child=DependencyCheckSerializer())


class MetaSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.CharField()
    environment = serializers.CharField()
    ai_provider = serializers.CharField()
    ai_mock_mode = serializers.BooleanField()
    features = serializers.DictField(child=serializers.BooleanField())
