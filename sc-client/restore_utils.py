import mimetypes
import os
import json
import logging
import base64

import network_utils as scnet

def is_previewable_file(file_path: str) -> bool:
    """Determine if a file can be previewed based on its mimetype and extension"""
    
    # Initialize mimetypes database
    mimetypes.init()
    
    # Get extension first - start with this since it's simpler
    ext = os.path.splitext(file_path)[1].lower()
    
    # Define previewable extensions
    previewable_extensions = {
        # Documents
        '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.rtf',
        # Data files
        '.csv', '.json', '.xml', '.yml', '.yaml',
        # Images
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
        # Text/Code
        '.py', '.js', '.html', '.css', '.md', '.log', '.sql',
        # Config
        '.ini', '.cfg', '.conf',
        # Media
        '.mp3', '.wav', '.mp4', '.avi', '.mov'
    }
    
    # First check extension
    is_previewable_by_ext = ext in previewable_extensions
    if is_previewable_by_ext:
        return True
        
    # Get mimetype as backup
    mime_type, _ = mimetypes.guess_type(file_path)
    
    # Check mimetype if available
    if mime_type:
        main_type = mime_type.split('/')[0]
        is_previewable_by_mime = main_type in {'text', 'image', 'audio', 'video'} or mime_type == 'application/pdf'
        if is_previewable_by_mime:
            return True
            
    return False

def get_preview_path(file_path: str) -> str:
    """Get the temporary path for file preview"""
    preview_dir = os.path.join(os.getenv('APPDATA'), 'Stormcloud', 'restore_preview')
    # Use the full path structure to maintain uniqueness
    preview_path = os.path.join(preview_dir, file_path.lstrip('/'))
    return preview_path

def restore_file(file_path, api_key, agent_id, version_id=None, preview_path=None):
    """
    Restore file either to original location or preview location
    
    Args:
        file_path: Path to restore (source)
        api_key: API key for authentication
        agent_id: Agent ID for authentication
        version_id: Optional version ID
        preview_path: If provided, write to this location instead of original path
    """
    path_for_request = base64.b64encode(str(file_path).encode("utf-8")).decode('utf-8')

    restore_file_request_data = json.dumps({
        'request_type': 'restore_file',
        'file_path': path_for_request,
        'api_key': api_key,
        'agent_id': agent_id,
        'version_id': version_id
    })

    status_code, response_data = scnet.tls_send_json_data_get(
        restore_file_request_data,
        200,
        show_json=False
    )
    
    logging.info("Status code returned: {}".format(status_code))
    logging.info("Response data returned: {}".format(response_data))

    if response_data and 'file_content' in response_data:
        file_content = base64.b64decode(response_data['file_content'])
        # Use preview_path if provided, otherwise use original file_path
        destination = preview_path if preview_path else file_path
        return write_file_to_disk(file_content, destination)
            
    logging.warning("Failed to get response from restore_file request")
    return False

def restore_large_file(file_path: str, api_key: str, agent_id: str, 
                      progress_callback=None, should_stop=None) -> bool:
    """
    Restore a large file using chunked downloads
    
    Args:
        file_path: Path to restore the file to
        api_key: API authentication key
        agent_id: Agent identifier
        progress_callback: Optional callback(percent)
        should_stop: Optional threading.Event for cancellation
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        temp_path = f"{file_path}.tmp"
        chunk_size = 16 * 1024 * 1024  # 16MB chunks
        
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(temp_path, 'wb') as f:
            offset = 0
            total_size = None
            
            while True:
                if should_stop and should_stop.value:
                    logging.info(f"Cancelling chunked restore of {file_path}")
                    return False
                    
                # Request chunk
                restore_request = json.dumps({
                    'request_type': 'restore_file',
                    'file_path': base64.b64encode(str(file_path).encode("utf-8")).decode('utf-8'),
                    'api_key': api_key,
                    'agent_id': agent_id,
                    'offset': offset,
                    'length': chunk_size
                })
                
                status_code, response = scnet.tls_send_json_data_get(
                    restore_request,
                    200,
                    show_json=False
                )
                
                if not response or 'file_content' not in response:
                    logging.error(f"Invalid response for chunk at offset {offset}")
                    logging.error(f"Response: {response}")
                    return False
                    
                chunk = base64.b64decode(response['file_content'])
                if not chunk:
                    break
                    
                f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
                
                offset += len(chunk)
                
                # Get total size from first response
                if total_size is None and 'total_size' in response:
                    total_size = int(response['total_size'])
                    
                if progress_callback and total_size:
                    progress_callback((offset / total_size) * 100)
                    
        # Verify final size if we know it
        if total_size is not None:
            actual_size = os.path.getsize(temp_path)
            if actual_size != total_size:
                logging.error(f"Size mismatch: expected {total_size}, got {actual_size}")
                os.remove(temp_path)
                return False
                
        # Atomic rename
        os.replace(temp_path, file_path)
        return True
        
    except Exception as e:
        logging.error(f"Error in chunked restore: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return False

def write_file_to_disk(file_content, destination_path):
    """Write file content to disk at the specified destination"""
    try:
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        with open(destination_path, 'wb') as outfile:
            outfile.write(file_content)
            
        logging.info(f"Successfully wrote file to {destination_path}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to write file to {destination_path}: {e}")
        return False