(function () {
	const CARD_LABELS = {
		"Bulk Pre Production for Sales Orders": "Bulk Pre Prod",
		"Production Plans from Bulk Pre Production": "Plans from Bulk PP",
		"Production Plans Not Started": "Plans Submitted",
		"Production Plans Completed": "Plans Completed",
	};

	function is_planning_workspace() {
		return frappe.get_route_str() === "Workspaces/Planning";
	}

	function get_planning_cards() {
		return $(".number-widget-box").filter((_, element) => {
			const title = $(element).find(".widget-title").text().trim();
			return (
				Object.prototype.hasOwnProperty.call(CARD_LABELS, title) ||
				Object.values(CARD_LABELS).includes(title)
			);
		});
	}

	function normalize_card_numbers() {
		get_planning_cards().each((_, element) => {
			const $card = $(element);
			const $title = $card.find(".widget-title .ellipsis");
			const raw_title = $title.text().trim();
			if (CARD_LABELS[raw_title]) {
				$title.text(CARD_LABELS[raw_title]);
				$title.attr("title", CARD_LABELS[raw_title]);
			}

			const $number = $card.find(".number");
			const raw = $number.text().trim();
			if (!raw) return;

			const plain = raw.replace(/[^\d.-]/g, "");
			if (!plain) return;

			const whole = plain.includes(".") ? plain.split(".")[0] : plain;
			$number.text(whole || "0");
		});
	}

	function setup_planning_cards() {
		if (!is_planning_workspace()) return;

		frappe.after_ajax(() => {
			setTimeout(() => {
				normalize_card_numbers();
			}, 150);
		});
	}

	frappe.router.on("change", setup_planning_cards);
	$(document).on("page-change", setup_planning_cards);
})();
