import os
import json
import base64
import logging
import anthropic
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

def handle_summarize_file_request(data: Dict[str, Any]) -> Tuple[int, str]:
    """Handle request to summarize file using Claude API."""
    try:
        # Decode file content from base64
        try:
            filepath = base64.b64decode(data['filepath']).decode('utf-8')
            content = base64.b64decode(data['content']).decode('utf-8')
        except:
            logger.error("Failed to decode file content")
            return 400, json.dumps({'success': False, 'message': 'Invalid file content'})
            
        # Create API client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("Claude API key not found in environment")
            return 500, json.dumps({'success': False, 'message': 'Server configuration error'})
            
        client = anthropic.Anthropic(api_key=api_key)

        # Prepare message with file content
        file_message = f"""<document>
<source>{filepath}</source>
<document_content>
{content}
</document_content>
</document>"""

        system_prompt = """
You are a friendly, professional AI assistant for a cloud backup services product named "Stormcloud", which is owned by the company "Dark Age Technology Group, LLC", a Maryland LLC.

Your objective is to generate a well-structured, comprehensive overview of any file information provided to you.

As your goal is to produce a well-structured report for the user, you will never ask follow up questions. This particular task is not designed to be a conversational thread; it's meant to be a standalone report for users.
        """
        
        # Make API call
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            temperature=0,
            system=system_prompt,
            messages=[{
                "role": "user", 
                "content": f"I've uploaded some files for analysis. These files are available through the window.fs.readFile API. Please analyze them programmatically.\n\nThe files are:\n\n{file_message}"
            }]
        )
        
        # Return successful response
        return 200, json.dumps({
            'success': True,
            'data': {
                'summary': message.content[0].text
            }
        })

    except Exception as e:
        logger.error(f"Error processing summary request: {e}", exc_info=True)
        return 500, json.dumps({
            'success': False,
            'message': f"Server error: {str(e)}"
        })