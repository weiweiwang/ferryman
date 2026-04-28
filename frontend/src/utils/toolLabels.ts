export const ToolLabels: Record<string, string> = {
    // Web Actions
    navigate: "navigating_to",
    get_distilled_dom: "distilling_content",
    click: "clicking_element",
    type: "typing_text",
    
    // Command Actions
    execute_applescript: "executing_applescript",
    run_bash: "running_bash",

    // File Actions
    read_file: "reading_file",
    write_file: "writing_file",
    list_files: "reading_directory",
    search_files: "searching_files",

    // Session Actions
    create_task: "creating_task",
    get_task: "getting_task",
    update_task_status: "updating_task",
    list_tasks: "listing_tasks",

    // Email Actions
    send_email: "sending_email",

    // Image Actions
    generate_image: "generating_image",

    // Skill Actions
    list_skills: "listing_skills",
    install_skill: "installing_skill",
    read_skill: "reading_skill",
};

export function getFriendlyToolName(rawToolName: string, t: (key: string) => string): string {
    const translationKey = ToolLabels[rawToolName];
    if (translationKey) {
        // Fallback to title case if translation key doesn't resolve to a real translated string
        const translated = t(`tools.${translationKey}`);
        if (!translated.includes(`tools.`)) {
            return translated;
        }
    }
    
    // Title-case fallback: "some_tool_name" → "Some Tool Name"
    return rawToolName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
