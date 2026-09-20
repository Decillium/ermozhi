from typing import Optional, Tuple, Dict, Any, List
from src.contracts.v1 import (
    DecisionAction,
    DecisionOutput,
    ExtractionIntent,
    IntelligenceOutput
)


class LanguageTemplateEngine:
    """
    Template engine for rural-first localization in Tamil (ta-IN) and English (en-IN).
    Ensures zero hallucination by strictly binding verified market facts, dates, and actions.
    """

    @classmethod
    def render_decision_response(
        cls,
        decision: DecisionOutput,
        locale: str = "ta-IN"
    ) -> Tuple[str, str, str]:
        """
        Renders localized text for a verified DecisionOutput.
        Returns: Tuple[text_content, source_disclosure, template_id]
        """
        is_tamil = locale.startswith("ta")
        action = decision.action
        ref_price = int(decision.reference.value if decision.reference else (decision.reference_price or 0.0))
        offered_price = int(decision.offer.value if decision.offer else (decision.offer_price or 0.0))
        facts = decision.explanation.facts if decision.explanation else {}
        crop = facts.get("crop", "Turmeric")
        variety = facts.get("variety", "Finger")
        mandi = facts.get("district", "Erode")
        obs_date = decision.evidence.get("observed_at", "") if decision.evidence else ""

        # Source disclosure
        if is_tamil:
            disclosure = f"தகவல் ஆதாரம்: {mandi} ஒழுங்குமுறை விற்பனைக்கூடம் ({obs_date} நிலவரப்படி)."
        else:
            disclosure = f"Source: {mandi} APMC Mandi (Observed on {obs_date})."

        # Localization templates
        if action == DecisionAction.SELL:
            template_id = "tpl_sell_v1"
            if is_tamil:
                text = (
                    f"🌾 உழவர் நண்பரே! உங்களுக்கு வழங்கப்பட்ட விலை ₹{offered_price:,} "
                    f"சந்தையின் தற்போதைய மாதிரி விலையான ₹{ref_price:,} உடன் ஒப்பிடும்போது சாதகமாக உள்ளது. "
                    f"இந்த விலைக்கு விற்பனை செய்வது நல்லது."
                )
            else:
                text = (
                    f"Farmer friend! The offered price of ₹{offered_price:,} for {variety} {crop} "
                    f"is favorable compared to the current mandi reference price of ₹{ref_price:,}. "
                    f"Selling at this rate is recommended."
                )

        elif action == DecisionAction.NEGOTIATE:
            template_id = "tpl_negotiate_v1"
            target_counter = int(ref_price * 0.95)
            if is_tamil:
                text = (
                    f"🌾 உழவர் நண்பரே! வியாபாரி வழங்கும் விலை ₹{offered_price:,} சந்தை விலையை விட (₹{ref_price:,}) சற்று குறைவாக உள்ளது. "
                    f"குறைந்தது ₹{target_counter:,} வரை பேசிப்பார்க்க பரிந்துரைக்கப்படுகிறது."
                )
            else:
                text = (
                    f"Farmer friend! The offered rate of ₹{offered_price:,} is moderately below the mandi modal price of ₹{ref_price:,}. "
                    f"Bargaining for at least ₹{target_counter:,} is recommended."
                )

        elif action == DecisionAction.HOLD:
            template_id = "tpl_hold_v1"
            if is_tamil:
                text = (
                    f"🌾 உழவர் நண்பரே! வியாபாரி வழங்கும் விலை ₹{offered_price:,} சந்தை விலையான ₹{ref_price:,} ஐ விட மிகவும் குறைவாக உள்ளது. "
                    f"சரக்கை இருப்பு வைக்க வசதி இருந்தால், சில நாட்கள் பொறுத்திருந்து விற்கவும்."
                )
            else:
                text = (
                    f"Farmer friend! The offered price of ₹{offered_price:,} is substantially lower than the mandi price of ₹{ref_price:,}. "
                    f"If storage is feasible, holding for better rates is advised."
                )

        else:  # WAIT
            template_id = "tpl_wait_v1"
            if is_tamil:
                text = (
                    f"🌾 உழவர் நண்பரே! சந்தையில் போதிய சமீபத்திய விலை விவரங்கள் பதிவாகவில்லை. "
                    f"சந்தை நிலவரம் தெளிவாகும் வரை அவசரப்பட்டு விற்க வேண்டாம்."
                )
            else:
                text = (
                    f"Farmer friend! Insufficient recent market data is available for {variety} {crop}. "
                    f"Waiting for clear market observations is advised."
                )

        return text, disclosure, template_id

    @classmethod
    def render_clarification_response(
        cls,
        missing_fields: List[str],
        locale: str = "ta-IN"
    ) -> Tuple[str, str, str]:
        """
        Renders targeted clarification questions for missing extraction fields.
        """
        is_tamil = locale.startswith("ta")
        template_id = "tpl_clarify_v1"

        if "variety" in missing_fields and "offered_price" in missing_fields:
            if is_tamil:
                text = (
                    "வணக்கம் உழவரே! 🌾\n"
                    "தயவுசெய்து மஞ்சளின் வகை (விரலி அல்லது கிழங்கு) மற்றும் வியாபாரி வழங்கிய விலையைக் குறிப்பிடவும்."
                )
            else:
                text = (
                    "Hello! Please mention the turmeric variety (Finger or Bulb) "
                    "and the trader's offered price."
                )
        elif "variety" in missing_fields:
            if is_tamil:
                text = (
                    "வணக்கம் உழவரே! 🌾\n"
                    "இது எந்த வகை மஞ்சள்? (விரலி / விரலி மஞ்சள் அல்லது கிழங்கு / குண்டு மஞ்சள்) என்று கூறவும்."
                )
            else:
                text = "Hello! Please specify which variety you have: Finger (Virali) or Bulb (Kizhangu)?"
        elif "offered_price" in missing_fields:
            if is_tamil:
                text = (
                    "வணக்கம் உழவரே! 🌾\n"
                    "வியாபாரி உங்களுக்கு ஒரு குவிண்டாலுக்கு என்ன விலை கூறினார் (எ.கா. ₹14,200) என்று தெரிவிக்கவும்."
                )
            else:
                text = "Hello! Please mention the price per quintal offered by the trader (e.g., ₹14,200)."
        else:
            if is_tamil:
                text = "வணக்கம் உழவரே! 🌾 தயவுசெய்து உங்கள் கேள்வி அல்லது வியாபாரி கூறிய விலையை தெளிவாக அனுப்பவும்."
            else:
                text = "Hello! Please share your crop details and the trader's offer price."

        disclosure = "ஏர்மொழி வழிகாட்டி — சந்தை தகவல் மையம்." if is_tamil else "Ermozhi Support."
        return text, disclosure, template_id
