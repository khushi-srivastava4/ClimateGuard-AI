"""Prompt generation for the agronomy advisor."""

from __future__ import annotations


LANGUAGE_NAMES = {"bn": "Bengali", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "kn": "Kannada", "pa": "Punjabi"}


def build_system_prompt(language: str, crop: str) -> str:
    crop_name = crop or "crop"
    if language.lower() in LANGUAGE_NAMES:
        return (
            f"You are an agronomy advisor. Provide a brief 2-week advisory for {crop_name}. "
            "Consider weather, soil, and mandi conditions. "
            "Cite every numeric value with source name, timestamp, and parameters. "
            f"Keep the response under 150 words and write it in {LANGUAGE_NAMES[language.lower()]}."
        )
    if language.lower() == "hi":
        return (
            f"आप एक कृषि सलाहकार हैं। 2-सप्ताह का संक्षिप्त सलाह दें। "
            f"{crop_name} के लिए मौसम, मिट्टी और mandi स्थिति पर विचार करें। "
            "हर संख्यात्मक मान के लिए स्रोत नाम, टाइमस्टैम्प, और पैरामीटर को उद्धृत करें। "
            "उत्तर 150 शब्द से छोटा रखें। हिंदी में लिखें।"
        )
    return (
        f"You are an agronomy advisor. Provide a brief 2-week advisory for {crop_name}. "
        "Consider weather, soil, and mandi conditions. "
        "Cite every numeric value with source name, timestamp, and parameters. "
        "Keep the response under 150 words and in English."
    )
